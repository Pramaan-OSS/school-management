"""Published intake options for signed-in applicants."""
import frappe
from frappe import _
from frappe.utils import getdate, today


def get_context(context):
    context.no_cache = 1


def _application_details(name):
    register = frappe.get_doc("Admission Register", name)
    if (register.docstatus != 1 or not register.published
        or register.status != "Admission Open"
        or getdate(register.start_date) > getdate(today())
        or getdate(register.end_date) < getdate(today())):
        frappe.throw(_("This admission is not open for applications."))
    return register


@frappe.whitelist()
def get_application_options():
    rows = frappe.get_all("Admission Register", filters={
        "docstatus": 1, "published": 1, "status": "Admission Open",
        "start_date": ["<=", today()], "end_date": [">=", today()],
    }, fields=["name", "title"], order_by="start_date asc", limit_page_length=100)
    result = []
    for row in rows:
        register = _application_details(row.name)
        courses = ([register.course] if register.admission_based_on == "Course"
                   else [entry.course for entry in register.courses])
        result.append({"name": register.name, "title": register.title, "courses": courses})
    return result
