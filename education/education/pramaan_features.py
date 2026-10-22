"""The approved outside features, all through the single Pramaan client.

Each action is a staff or instructor click; nothing runs on a schedule, and
nothing sends or creates without the person choosing it. Unavailable
capabilities show their plain surface message from the client.
"""

import hashlib
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote

import frappe
from frappe import _
from education.pramaan import PramaanClient, PramaanError

STAFF_ROLES = ["System Manager", "Education Manager", "Instructor", "Academics User"]


def client():
    pramaan = PramaanClient()
    try:
        pramaan.require_configured()
    except PramaanError as error:
        _refuse(error)
    return pramaan


def _refuse(error):
    """Surface only the client's plain, self-contained messages."""
    frappe.throw(_(str(error)))


def _staff():
    frappe.only_for(STAFF_ROLES)


def _end_user_ref(user=None):
    """A stable local reference that is never an email or a name."""
    digest = hashlib.md5((user or frappe.session.user).encode()).hexdigest()[:16]
    return "edu-" + digest


@frappe.whitelist(methods=["POST"])
def start_app_connection(connection):
    _staff()
    doc = frappe.get_doc("Connected App", connection)
    doc.check_permission("write")
    if not doc.pramaan_app_id:
        frappe.throw(_("Choose an application ID before connecting."))
    try:
        return _action("apps.connection.start", {
            "app": doc.pramaan_app_id,
            "endUserRef": _end_user_ref(),
            "redirectUrl": frappe.utils.get_url("/app/connected-app/" + quote(doc.name, safe="")),
        })
    except PramaanError as error:
        _refuse(error)


def _schedule_bounds(doc):
    from frappe.utils import to_timedelta, getdate
    day = datetime.combine(getdate(doc.schedule_date), datetime.min.time())
    start = day + to_timedelta(doc.from_time)
    end = day + to_timedelta(doc.to_time)
    if end <= start:
        frappe.throw(_("The end time must be after the start time."))
    return start, end


def _action(capability, inputs, *, reuse=False):
    """Save intent before an outside effect; never repeat an uncertain action."""
    payload = json.dumps(inputs, sort_keys=True)
    previous = frappe.get_all(
        "Pramaan Outbox", filters={"capability": capability, "payload": payload},
        fields=["name", "state", "result"], order_by="creation desc", limit=1,
    )
    if previous:
        if previous[0].state in {"Sending", "Uncertain"}:
            _refuse(PramaanError("check_action", uncertain=True))
        if reuse and previous[0].state == "Accepted":
            return json.loads(previous[0].result)
    pramaan = client()
    estimate = pramaan.estimate(capability, inputs)
    if not estimate["can_run"]:
        frappe.throw(_("This action is not available yet."))
    intent = frappe.get_doc({
        "doctype": "Pramaan Outbox", "capability": capability, "payload": payload,
        "idempotency_key": str(uuid.uuid4()), "state": "Sending",
        "requested_by": frappe.session.user,
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    try:
        result = pramaan.call(capability, inputs, idempotency_key=intent.idempotency_key)
    except PramaanError as error:
        intent.db_set({"state": "Uncertain" if error.uncertain else "Failed", "error": str(error)})
        frappe.db.commit()
        raise
    except Exception:
        intent.db_set({"state": "Uncertain", "error": "Check the action before trying again."})
        frappe.db.commit()
        raise PramaanError("check_action", uncertain=True) from None
    result.pop("hostUrl", None)
    intent.db_set({"state": "Accepted", "result": json.dumps(result), "error": ""})
    frappe.db.commit()
    return result


# --- Guardian alerts -------------------------------------------------------


def _guardians_of(student):
    for row in frappe.get_all("Student Guardian", filters={"parent": student}, fields=["guardian"]):
        guardian = frappe.db.get_value(
            "Guardian", row.guardian, ["name", "email_address", "mobile_number", "disable_school_messages"], as_dict=True)
        if guardian and not guardian.disable_school_messages:
            yield guardian


@frappe.whitelist()
def send_guardian_alerts(student_batch: str, date: str, message: str, channel: str = "email",
                         subject: str | None = None, students: str | None = None):
    """Notify the guardians of students absent on a date. One explicit send."""
    _staff()
    if not message or not message.strip():
        frappe.throw(_("Write the message to send."))
    if channel not in {"email", "sms"}:
        frappe.throw(_("Choose email or sms."))
    frappe.get_doc("Student Batch Name", student_batch).check_permission("write")
    names = json.loads(students) if students else [
        row.student for row in frappe.get_all(
            "Student Attendance",
            filters={"student_batch": student_batch, "date": date, "status": "Absent", "docstatus": 1},
            fields=["student"], distinct=True,
        )
    ]
    if students:
        frappe.throw(_("Use the saved absence list for this batch and date."))
    recipients = []
    skipped = 0
    seen = set()
    for student in names:
        found = False
        for guardian in _guardians_of(student):
            key = guardian.mobile_number if channel == "sms" else guardian.email_address
            found = found or bool(key)
            if key and key not in seen:
                seen.add(key)
                recipients.append(key)
        skipped += not found
    if not recipients:
        return {"queued": 0, "skipped": len(names)}

    pramaan = client()
    pramaan.require_configured()
    sent = 0
    if channel == "email":
        from education.integrations.pramaan_mail import sendmail as pramaan_sendmail
        for address in recipients:
            try:
                pramaan_sendmail(recipients=[address], subject=subject or _("Absence notice"),
                                 message="<p>{0}</p>".format(frappe.utils.escape_html(message)))
            except PramaanError as error:
                _refuse(error)
            sent += 1
    else:
        for number in recipients:
            try:
                _action("sms.send", {"to": number, "body": message}, reuse=True)
            except PramaanError as error:
                _refuse(error)
            sent += 1
    return {"queued": sent, "skipped": skipped}


@frappe.whitelist()
def translate_message(text: str, target_language: str):
    """Translate a message before sending; the original stays beside it."""
    _staff()
    if not text.strip() or not target_language.strip():
        frappe.throw(_("Give the text and the target language."))
    pramaan = client()
    pramaan.require_configured()
    try:
        result = pramaan.call("text.translate", {"text": text, "targetLanguage": target_language.strip().lower()})
    except PramaanError as error:
        _refuse(error)
    return {"text": result.get("text", "")}


# --- Online class rooms ----------------------------------------------------


@frappe.whitelist()
def create_class_meeting(subject_schedule: str):
    """Create an online meeting room for a scheduled class."""
    _staff()
    doc = frappe.get_doc("Subject Schedule", subject_schedule)
    doc.check_permission("write")
    if doc.get("meeting_room_ref"):
        return get_class_meeting(subject_schedule)
    if doc.get("meeting_url"):
        return {"url": doc.meeting_url}
    app = frappe.db.get_single_value("Education Settings", "meetings_app")
    if not app:
        frappe.throw(_("Set the meeting app handle in Education Settings first."))
    start, end = _schedule_bounds(doc)
    timezone = frappe.db.get_single_value("System Settings", "time_zone") or "UTC"
    pramaan = client()
    pramaan.require_configured()
    inputs = {"app": app, "endUserRef": _end_user_ref(),
              "title": doc.title or doc.subject,
              "start": start.replace(tzinfo=ZoneInfo(timezone)).isoformat(),
              "durationMinutes": int((end - start).total_seconds() // 60), "timezone": timezone}
    try:
        result = _action("meetings.room.create", inputs, reuse=True)
    except PramaanError as error:
        _refuse(error)
    url = result.get("joinUrl") or ""
    if not url:
        frappe.throw(_("The meeting room could not be created. Please try again."))
    doc.db_set({"meeting_room_ref": result.get("ref", ""), "meeting_url": url})
    return {"url": url}


@frappe.whitelist()
def get_class_meeting(subject_schedule: str):
    _staff()
    doc = frappe.get_doc("Subject Schedule", subject_schedule)
    doc.check_permission("read")
    try:
        result = client().call("meetings.room.get", {
            "ref": doc.meeting_room_ref,
            "endUserRef": _end_user_ref(),
        })
    except PramaanError as error:
        _refuse(error)
    return {"url": result.get("joinUrl", ""), "status": result.get("status", "")}


# --- Calendar entries ------------------------------------------------------


@frappe.whitelist()
def sync_calendar_entry(doctype: str, name: str):
    """Create or update a calendar entry for a class or an exam."""
    _staff()
    if doctype not in {"Subject Schedule", "Assessment Plan"}:
        frappe.throw(_("Invalid document provided."))
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("write")
    inbox = frappe.db.get_single_value("Education Settings", "calendar_inbox")
    if not inbox:
        frappe.throw(_("Set the school calendar inbox in Education Settings first."))
    start, end = _schedule_bounds(doc)
    timezone = frappe.db.get_single_value("System Settings", "time_zone") or "UTC"
    title = doc.get("title") or doc.get("assessment_name") or doc.subject
    attendees = set()
    if doc.get("faculty"):
        email = frappe.db.get_value("Faculty", doc.faculty, "email_address")
        if email:
            attendees.add(email)
    for row in frappe.get_all("Course Enrollment", filters={"student_batch": doc.student_batch, "docstatus": 1},
                              fields=["student"]):
        for guardian in _guardians_of(row.student):
            if guardian.email_address:
                attendees.add(guardian.email_address)
    if len(attendees) > 100:
        frappe.throw(_("A calendar entry can invite at most 100 people."))
    inputs = {"inbox": inbox, "title": title, "start": start.isoformat(), "end": end.isoformat(),
              "timezone": timezone, "allDay": False,
              "attendees": [{"email": email} for email in sorted(attendees)], "sendInvites": True}
    capability = "calendar.event.create"
    if doc.get("calendar_event_ref"):
        capability = "calendar.event.update"
        inputs["ref"] = doc.calendar_event_ref
    try:
        result = _action(capability, inputs, reuse=True)
    except PramaanError as error:
        _refuse(error)
    ref = result.get("ref") or doc.get("calendar_event_ref")
    if ref and ref != doc.get("calendar_event_ref"):
        doc.db_set("calendar_event_ref", ref)
    return {"ref": ref}


# --- Admission document prefill -------------------------------------------

APPLICANT_FIELDS = ["first_name", "last_name", "email_address", "student_mobile_number",
                    "address_line_1", "city", "state", "pincode"]


@frappe.whitelist()
def prefill_applicant(applicant: str, file_url: str):
    """Read an uploaded admission form and propose field values; never saves."""
    _staff()
    doc = frappe.get_doc("Student Applicant", applicant)
    doc.check_permission("write")
    file_doc = frappe.get_doc("File", {"file_url": file_url} if file_url.startswith("/") else file_url)
    file_doc.check_permission("read")
    if file_doc.attached_to_doctype != "Student Applicant" or file_doc.attached_to_name != applicant:
        frappe.throw(_("Choose a document attached to this applicant."))
    content = file_doc.get_content()
    if isinstance(content, str):
        content = content.encode()
    if not content or len(content) > 10 * 1024 * 1024:
        frappe.throw(_("Choose a document between 1 byte and 10 MB."))
    extension = (file_doc.file_name.rsplit(".", 1)[-1] if "." in file_doc.file_name else "")
    if not extension.isalnum() or not 1 <= len(extension) <= 8:
        frappe.throw(_("Choose a document with a normal file extension."))
    import base64
    schema = {"type": "object", "properties": {
        field: {"type": "string"} for field in APPLICANT_FIELDS}, "required": APPLICANT_FIELDS}
    pramaan = client()
    pramaan.require_configured()
    try:
        result = pramaan.call("document.extract", {
            "content": base64.b64encode(content).decode(), "extension": extension.lower(),
            "schema": schema,
        })
    except PramaanError as error:
        _refuse(error)
    # The completed extraction wraps the requested fields in data.
    # Keep the raw response available while proposing only reviewed fields.
    return {"extraction": result.get("data", result), "source": result}


# --- Quiz drafting ---------------------------------------------------------


@frappe.whitelist()
def draft_quiz_questions(quiz: str, count: int = 5):
    """Draft questions for the instructor to edit; nothing is saved."""
    _staff()
    doc = frappe.get_doc("Quiz", quiz)
    doc.check_permission("write")
    count = max(1, min(int(count), 10))
    course = frappe.db.get_value("Course", doc.course, "course_name") if doc.get("course") else ""
    brief = _(
        "Draft {0} multiple-choice quiz questions for the course {1}, quiz {2}. "
        "Number them. Give four options each and mark the correct one."
    ).format(count, course or "-", doc.name)
    pramaan = client()
    pramaan.require_configured()
    try:
        result = pramaan.call("llm.complete", {
            "maxTokens": max(256, count * 256),
            "messages": [
                {"role": "system", "content": "You draft quiz questions for teachers. Answer with numbered questions only."},
                {"role": "user", "content": brief},
            ],
        })
    except PramaanError as error:
        _refuse(error)
    return {"text": result.get("text", ""), "finishReason": result.get("finishReason", "")}


# --- Fee reminders ---------------------------------------------------------


@frappe.whitelist()
def send_fee_reminder(fees: str, channel: str = "email"):
    """Send the saved payment link to the payer again over the chosen channel."""
    frappe.only_for(["System Manager", "Education Manager", "Academics User"])
    doc = frappe.get_doc("Fees", fees)
    doc.check_permission("write")
    if channel not in {"email", "sms"}:
        frappe.throw(_("Choose email or sms."))
    if not doc.payment_link_id:
        frappe.throw(_("Send the payment request first; the reminder reuses its saved link."))
    pramaan = client()
    pramaan.require_configured()
    try:
        reference_field = "ref" if doc.payment_link_id.startswith(("ref_", "rh_")) else "paymentLinkId"
        result = _action("payments.payment-link.notify",
                         {"channel": channel, reference_field: doc.payment_link_id})
    except PramaanError as error:
        _refuse(error)
    return {"sent": result.get("sent")}
