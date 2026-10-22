"""Bank transfers on authorized school invoices and fees, using the existing client."""
import hashlib
import json
import frappe
from education.education.billing import client, get_details, _check_permission
from education.education.transfers import Transfer, request_body, EXPONENTS
from education.pramaan import PramaanError


@frappe.whitelist(methods=["POST"])
def transfer(docname: str, doctype: str = "Sales Invoice", operation: str = "status",
             confirmation: str | None = None, bank_country: str | None = None):
    if frappe.session.user == "Guest" or doctype not in {"Sales Invoice", "Fees"}:
        frappe.throw("Not permitted", frappe.PermissionError)
    doc = frappe.get_doc(doctype, docname)
    if doctype == "Sales Invoice":
        _check_permission(get_details(docname))
    else:
        doc.check_permission("write")
    frappe.db.sql(f"select name from `tab{doctype}` where name=%s for update", docname)
    doc.reload()
    if doc.docstatus != 1:
        frappe.throw("Choose a submitted invoice or fee.")
    name = "bank-transfer-" + hashlib.sha256((doctype + ":" + docname).encode()).hexdigest()[:32]
    if frappe.db.exists("Payment Record", name):
        record = frappe.get_doc("Payment Record", name)
    else:
        record = frappe.get_doc({"doctype": "Payment Record", "student": doc.student,
            "transfer_doctype": doctype, "transfer_document": docname,
            "against_invoice": docname if doctype == "Sales Invoice" else None,
            "status": "Awaiting", "currency": doc.currency})
        record.insert(ignore_permissions=True, set_name=name)
    state = json.loads(record.bank_transfer_data or "{}")
    def save(value, durable):
        record.db_set("bank_transfer_data", json.dumps(value))
        if durable:
            frappe.db.commit()
    try:
        flow = Transfer(client(), state, save)
        body = state.get("body", {})
        if operation in {"create", "confirm"}:
            # Bind approval to the current bill; never trust a browser's amount.
            amount = doc.outstanding_amount
            if operation == "create" or state.get("intent", {}).get("action") == "create":
                if amount <= 0:
                    frappe.throw("This invoice or fee is already paid.")
            else:
                amount = state.get("body", {}).get("amount", 0) / 10 ** EXPONENTS.get(doc.currency, 2)
            body = request_body(amount, doc.currency, doctype + " " + docname,
                                bank_country or state.get("body", {}).get("bankCountry"))
        if operation in {"create", "cancel"}:
            return flow.prepare(body, operation)
        if operation == "confirm":
            result = flow.confirm(confirmation, body, frappe.session.user)
        elif operation == "list":
            return flow.listed()
        elif operation == "status":
            result = flow.refresh(body)
        else:
            frappe.throw("Unknown bank transfer action.")
        if result.get("status") == "paid":
            _settle(record, state, doc)
        return result
    except PramaanError as error:
        frappe.throw(str(error))


def _settle(record, state, doc):
    """Book only a verified transfer; lock and payment reference prevent duplicate entries."""
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
    from frappe.utils import nowdate
    frappe.db.sql("select name from `tabPayment Record` where name=%s for update", record.name)
    record.reload()
    if record.status == "Captured":
        return
    existing = frappe.db.exists("Payment Entry", {"reference_no": record.name, "docstatus": 1})
    if not existing:
        user = frappe.session.user
        # The payer has already been authorized against this exact bill. Creating its
        # verified accounting entry is server work; students need no ledger-write role.
        try:
            frappe.set_user("Administrator")
            amount = state["body"]["amount"] / 10 ** EXPONENTS.get(state["body"]["currency"], 2)
            options = {"party_amount": amount}
            if doc.doctype == "Fees":
                options.update(party_type="Student", payment_type="Receive")
            entry = get_payment_entry(doc.doctype, doc.name, **options)
            entry.reference_no = record.name
            entry.reference_date = nowdate()
            entry.save(ignore_permissions=True)
            entry.submit()
        finally:
            frappe.set_user(user)
    record.db_set({"status": "Captured", "payment_id": state["ref"]})
