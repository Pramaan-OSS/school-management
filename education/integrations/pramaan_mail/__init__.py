"""Durable mail delivery through the application's single Pramaan client."""
import base64
import json
import mimetypes
import uuid
from email.utils import getaddresses

import frappe
from frappe import _

from education.pramaan import PramaanClient, PramaanError


def client():
    return PramaanClient()


def addresses(value):
    values = value if isinstance(value, list | tuple) else [value or ""]
    return list(dict.fromkeys(address for _, address in getaddresses(values) if address))


def sender_account(sender=None):
    """One school sender setting also covers framework-generated messages."""
    configured = frappe.db.get_single_value("Education Settings", "pramaan_sender")
    if not configured:
        configured = frappe.get_meta("Education Settings").get_field("pramaan_sender").default
    if len(addresses(configured)) != 1:
        frappe.throw(_("Set one name and email address in Email Sender."))
    return configured


AUTO_SUBMITTED = ("auto-generated", "auto-replied")


def marker_from(value):
    """A typed Auto-Submitted value from a caller header, else None.

    The platform only accepts "auto-generated" or "auto-replied"; an unknown
    app marker still marks the mail so recipients can suppress reply loops.
    """
    if value is True:
        return "auto-generated"
    raw = (value or "").split(";")[0].strip().lower()
    if not raw or raw == "no":
        return None
    return raw if raw in AUTO_SUBMITTED else "auto-generated"


def sendmail(recipients=None, sender=None, subject=None, message=None, **kwargs):
    """Queue a supported send atomically; the worker runs only after commit."""
    auto_submitted = marker_from(kwargs.get("auto_submitted"))
    if not auto_submitted:
        auto_submitted = marker_from((kwargs.get("email_headers") or {}).get(
            "X-Auto-Generated") or (kwargs.get("email_headers") or {}).get("Auto-Submitted"))
    inbox = sender_account(sender)
    payload = {"from": inbox, "to": addresses(recipients), "cc": addresses(kwargs.get("cc")),
               "bcc": addresses(kwargs.get("bcc")), "subject": subject or "Message"}
    if auto_submitted:
        payload["autoSubmitted"] = auto_submitted
    if kwargs.get("template"):
        message = frappe.render_template("templates/emails/" + kwargs["template"] + ".html", kwargs.get("args") or {})
    payload["html"] = message or kwargs.get("content") or ""
    if kwargs.get("as_markdown"):
        from frappe.utils import markdown
        payload["html"] = markdown(payload["html"])
    if kwargs.get("reply_to"):
        payload["replyTo"] = addresses(kwargs["reply_to"])[0]
    attachments = []
    for attachment in kwargs.get("attachments") or []:
        if attachment.get("file_url"):
            file_doc = frappe.get_doc("File", {"file_url": attachment["file_url"]})
            file_doc.check_permission("read")
            content = file_doc.get_content()
            filename = file_doc.file_name
        else:
            content = attachment.get("fcontent") or attachment.get("content") or b""
            filename = attachment.get("fname") or attachment.get("filename") or "attachment"
        if isinstance(content, str):
            content = content.encode()
        attachments.append({"filename": filename, "content": base64.b64encode(content).decode(),
                            "mimeType": mimetypes.guess_type(filename)[0] or "application/octet-stream"})
    payload["attachments"] = attachments
    if not (addresses(recipients) or payload.get("cc") or payload.get("bcc")):
        frappe.throw(_("Choose at least one recipient."))
    outbox = frappe.get_doc({"doctype": "Pramaan Outbox", "capability": "email.send",
                             "payload": json.dumps(payload), "idempotency_key": str(uuid.uuid4()),
                             "state": "Pending", "communication": kwargs.get("communication"),
                             "requested_by": frappe.session.user}).insert(ignore_permissions=True)
    frappe.enqueue(deliver, name=outbox.name, enqueue_after_commit=True)
    return frappe._dict(name=outbox.name, rfcMessageId=None, status="queued")


def deliver(name):
    """Persist intent before sending; uncertain outcomes never auto-retry."""
    outbox = frappe.get_doc("Pramaan Outbox", name)
    # Lock also stops a scheduler retry racing the initial worker.
    frappe.db.sql("select name from `tabPramaan Outbox` where name=%s for update", name)
    outbox.reload()
    if outbox.state != "Pending":
        return
    outbox.db_set("state", "Sending")
    frappe.db.commit()
    try:
        result = client().call(outbox.capability, json.loads(outbox.payload),
                               idempotency_key=outbox.idempotency_key)
    except PramaanError as error:
        outbox.db_set({"state": "Uncertain" if error.uncertain else "Failed", "error": str(error)})
        if outbox.communication:
            frappe.db.set_value("Communication", outbox.communication, "delivery_status", "Error")
        finish_legacy_queue(outbox, "Error")
        frappe.db.commit()
        return
    except Exception:
        outbox.db_set({"state": "Uncertain", "error": "Delivery could not be confirmed. Check before trying again."})
        finish_legacy_queue(outbox, "Error")
        frappe.db.commit()
        return
    if result.get("status") not in {"queued", "sent"}:
        outbox.db_set({"state": "Uncertain", "error": "Delivery could not be confirmed. Check before trying again."})
        finish_legacy_queue(outbox, "Error")
        frappe.db.commit()
        return
    outbox.db_set({"state": "Accepted", "message_id": result.get("rfcMessageId", ""),
                   "result_ref": result.get("ref", ""), "error": ""})
    if outbox.communication:
        frappe.db.set_value("Communication", outbox.communication,
                            {"delivery_status": "Sent"} | ({"message_id": result["rfcMessageId"]} if result.get("rfcMessageId") else {}))
    finish_legacy_queue(outbox, "Sent")
    frappe.db.commit()


def finish_legacy_queue(outbox, status):
    for name in frappe.get_all("Email Queue", filters={"pramaan_outbox": outbox.name}, pluck="name"):
        frappe.db.set_value("Email Queue", name, "status", status)


def drain():
    from frappe.utils import add_to_date, now_datetime
    stale = add_to_date(now_datetime(), minutes=-10)
    for name in frappe.get_all("Pramaan Outbox", filters={"state": "Sending", "modified": ("<", stale)}, pluck="name"):
        frappe.db.set_value("Pramaan Outbox", name, {"state": "Uncertain", "error": "Delivery was interrupted. Check before trying again."})
    frappe.db.commit()
    for name in frappe.get_all("Pramaan Outbox", filters={"state": "Pending"}, pluck="name", limit_page_length=50):
        deliver(name)


def install_transport(**kwargs):
    """Framework invites, welcome and password mail must use the same transport."""
    import frappe.email
    frappe.sendmail = sendmail
    frappe.email.sendmail = sendmail
