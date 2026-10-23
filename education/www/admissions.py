"""Public listing of published, current admission notices."""
import frappe
from frappe.utils import cint

from education.education.doctype.student_admission.student_admission import get_admission_list


def get_context(context):
    context.no_cache = 1
    context.title = frappe._("Student Admissions")
    context.start = max(0, cint(frappe.form_dict.get("start")))
    rows = get_admission_list("Student Admission", None, {}, context.start, 21)
    context.has_more = len(rows) > 20
    context.admissions = rows[:20]
