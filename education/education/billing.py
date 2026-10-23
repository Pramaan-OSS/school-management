"""Fee payments through the application's single Pramaan client.

The school's connected payment account takes the charges; the paying person
always finishes the payment themselves on the hosted page. The server only
creates the checkout, reads its state afterwards, and records the local
payment entry.
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from frappe import _
from frappe.utils import nowdate, validate_phone_number

from education.pramaan import PramaanClient, PramaanError

PAYABLE_DOCTYPE = "Sales Invoice"


def client():
    pramaan = PramaanClient()
    try:
        pramaan.require_configured()
    except PramaanError as error:
        _unavailable(error)
    return pramaan


def _unavailable(error):
    """Surface only the client's plain, self-contained messages."""
    frappe.throw(_(str(error)))


def get_details(docname):
    return frappe.db.get_value(
        PAYABLE_DOCTYPE,
        docname,
        ["name", "student", "currency", "outstanding_amount", "grand_total"],
        as_dict=1,
    )


def _check_permission(details):
    """A student may pay only their own invoice; staff need read permission."""
    if not details:
        frappe.throw(_("Invalid document provided."))
    user_student = frappe.db.get_value("Student", {"user": frappe.session.user}, "name")
    if user_student and details.student == user_student:
        return
    if not frappe.has_permission(PAYABLE_DOCTYPE, "read", doc=details.name):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _minor_units(amount):
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@frappe.whitelist()
def create_checkout(doctype: str, docname: str, billing_details: dict | None = None):
    """Create a hosted fee checkout for the session user and return its URL.

    Nothing is charged here: the paying person completes the payment on the
    hosted page themselves. Repeated requests for the same unpaid invoice
    reuse the saved checkout instead of creating a second one.
    """
    if doctype != PAYABLE_DOCTYPE:
        frappe.throw(_("Invalid document provided."))
    details = get_details(docname)
    _check_permission(details)
    if not details.outstanding_amount or details.outstanding_amount <= 0:
        frappe.throw(_("This invoice is already settled."))

    billing_details = billing_details or {}
    email = (billing_details.get("email") or "").strip() or frappe.session.user
    phone = (billing_details.get("mobile_number") or "").strip()
    if phone:
        validate_phone_number(phone_number=phone, throw=True)

    pramaan = client()
    pramaan.require_configured()
    try:
        if not pramaan.payment_account_ready():
            from education.pramaan import ConnectionRequired
            raise ConnectionRequired("payments.account.status", "payments")
    except PramaanError as error:
        _unavailable(error)

    pending = frappe.get_all(
        "Payment Record",
        filters={"against_invoice": details.name, "status": "Pending", "owner": frappe.session.user},
        fields=["name", "order_id", "checkout_url", "idempotency_key"],
        order_by="creation desc",
        limit=1,
    )
    if pending and pending[0].order_id and pending[0].checkout_url:
        return {"checkoutUrl": pending[0].checkout_url, "checkout": pending[0].name}

    key = pending[0].idempotency_key if pending and pending[0].idempotency_key else str(uuid.uuid4())
    record = frappe.get_doc(
        {
            "doctype": "Payment Record",
            "against_invoice": details.name,
            "status": "Pending",
            "amount": details.outstanding_amount,
            "currency": details.currency,
            "student": details.student,
            "email": email,
            "mobile": phone,
            "idempotency_key": key,
        }
    )
    for field in ("address_line_1", "address_line_2", "city", "state", "country", "pincode"):
        record.set(field, billing_details.get(field, ""))
    record.insert(ignore_permissions=True)
    return_url = frappe.utils.get_url() + "/student-portal/fees?checkout=" + record.name

    inputs = {
        "mode": "payment",
        "customerEmail": email,
        "successUrl": return_url,
        "cancelUrl": frappe.utils.get_url() + "/student-portal/fees",
        "lineItems": [
            {
                "name": _("Course fees"),
                "amount": _minor_units(details.outstanding_amount),
                "currency": (details.currency or "").lower()[:3],
                "quantity": 1,
            }
        ],
    }
    try:
        result = pramaan.run("payments.checkout.create", inputs, idempotency_key=key)
    except PramaanError as error:
        _unavailable(error)
    if not result.get("checkoutUrl"):
        frappe.throw(_("The payment page could not be created. Please try again."))
    record.db_set({"order_id": result.get("ref", ""), "checkout_url": result["checkoutUrl"]})
    return {"checkoutUrl": result["checkoutUrl"], "checkout": record.name}


@frappe.whitelist()
def get_checkout_status(checkout: str, session_result: str | None = None):
    """Read a hosted checkout's state and record a captured payment locally."""
    if not frappe.db.exists("Payment Record", checkout):
        frappe.throw(_("Invalid document provided."))
    record = frappe.get_doc("Payment Record", checkout)
    frappe.db.get_value("Student", {"user": frappe.session.user}, "name")
    if record.owner != frappe.session.user:
        invoice = get_details(record.against_invoice)
        _check_permission(invoice)

    if record.status == "Captured":
        return {"status": "paid", "paid": True}

    pramaan = client()
    pramaan.require_configured()
    inputs = {"ref": record.order_id}
    if session_result:
        inputs["sessionResult"] = session_result
    try:
        result = pramaan.call("payments.checkout.get", inputs)
    except PramaanError as error:
        _unavailable(error)

    state = result.get("status", "unknown")
    captured = next((p for p in result.get("payments", []) if p.get("status") == "captured"), None)
    if captured:
        _record_captured_payment(record, captured)
        return {"status": "paid", "paid": True}
    if state in {"cancelled", "expired", "refused"}:
        record.db_set({"status": "Failed",
                       "failure_description": _("The payment page was closed or the payment did not go through.")})
    return {"status": state, "paid": False}


def _record_captured_payment(record, captured):
    """Book the settled payment against the invoice, exactly once."""
    frappe.db.sql("select name from `tabPayment Record` where name=%s for update", record.name)
    record.reload()
    payment_id = captured.get("paymentId") or captured.get("ref") or record.order_id
    already = frappe.db.exists(
        "Payment Entry", {"reference_no": record.order_id, "docstatus": ("<", 2)}
    )
    record.db_set({"payment_id": payment_id, "status": "Captured", "failure_description": ""})
    if already:
        return
    try:
        frappe.flags.ignore_account_permission = True
        pe = get_payment_entry(PAYABLE_DOCTYPE, record.against_invoice)
        pe.reference_no = record.order_id
        pe.reference_date = nowdate()
        pe.posting_date = nowdate()
        pe.save(ignore_permissions=True)
        pe.submit()
    except Exception:
        frappe.log_error(
            title=_("Fee payment could not be recorded"),
            message=_("Payment {0} for invoice {1}").format(record.name, record.against_invoice),
        )


@frappe.whitelist()
def send_fee_payment_request(fees: str):
    """Create a payment link for a Fees document and email it to the payer."""
    frappe.only_for(["System Manager", "Education Manager", "Academics User"])
    doc = frappe.get_doc("Fees", fees)
    doc.check_permission("read")
    if not doc.contact_email:
        frappe.throw(_("Set a contact email on the Fees document first."))
    if not doc.grand_total or doc.grand_total <= 0:
        frappe.throw(_("This fee has no amount to request."))

    pramaan = client()
    pramaan.require_configured()
    try:
        if not pramaan.payment_account_ready():
            from education.pramaan import ConnectionRequired
            raise ConnectionRequired("payments.account.status", "payments")
    except PramaanError as error:
        _unavailable(error)

    if doc.payment_link:
        payment_url = doc.payment_link
    else:
        key = str(uuid.uuid4())
        if doc.payment_link_id:
            key = frappe.db.get_value(
                "Payment Record", {"order_id": doc.payment_link_id}, "idempotency_key") or key
        try:
            result = pramaan.run(
                "payments.payment-link.create",
                {
                    "amount": _minor_units(doc.grand_total),
                    "currency": (doc.currency or "").upper()[:3],
                    "description": _("Fee payment"),
                    "reference": doc.name,
                },
                idempotency_key=key,
            )
        except PramaanError as error:
            _unavailable(error)
        if not result.get("paymentUrl"):
            frappe.throw(_("The payment link could not be created. Please try again."))
        payment_url = result["paymentUrl"]
        doc.db_set({
            "payment_link_id": result.get("paymentLinkId") or result.get("ref", ""),
            "payment_link": payment_url,
        })

    from education.integrations.pramaan_mail import sendmail as pramaan_sendmail
    pramaan_sendmail(
        recipients=[doc.contact_email],
        subject=_("Fee payment request"),
        message="<p>{0}</p><p><a href=\"{1}\">{1}</a></p>".format(
            _("Please pay your outstanding fee:"), payment_url),
    )
    frappe.msgprint(_("Payment request queued for delivery."))
    return {"queued": True}


@frappe.whitelist(methods=["POST"])
def start_payment_connect(confirmation: str | None = None):
    """Compatibility entry point; account setup lives in the dedicated module."""
    from education.education import payment_account
    payment_account._admin()
    country = (frappe.db.get_single_value("Education Settings", "payment_connect_country") or "").strip()
    return payment_account.connect(confirmation=confirmation, country=country)


@frappe.whitelist(methods=["POST"])
def refresh_payment_account_status():
    from education.education import payment_account
    result = payment_account.status()
    labels = {"ready": "Ready", "incomplete": "Pending setup", "not_connected": "Not connected"}
    frappe.db.set_single_value("Education Settings", "payment_account_status", labels[result["state"]])
    return result
