# Copyright (c) 2015, Frappe Technologies and Contributors
# See license.txt


from frappe.tests.utils import FrappeTestCase

# test_records = frappe.get_test_records('Student Applicant')


class TestStudentApplicant(FrappeTestCase):
	pass


class TestPublicAdmissionDefaults(FrappeTestCase):
	def test_public_application_uses_school_owned_defaults(self):
		from unittest.mock import patch

		import frappe

		from education.education.doctype.student_applicant.student_applicant import StudentApplicant

		register = frappe._dict(admission_based_on="Course", course="Public Course",
			company="School", academic_year="Public Year", academic_term="Public Term",
			registration_fee=0, course_fee_amount=120)
		doc = StudentApplicant({"doctype": "Student Applicant", "admission_register": "Open Intake",
			"company": "Other Company", "course": "Other Course"})
		with patch("education.education.web_form.student_applicant.student_applicant._application_details", return_value=register), patch.object(frappe.db, "get_value", return_value="Public Fee Term"):
			doc.set_public_admission_details()
		self.assertEqual((doc.company, doc.course, doc.fee_term, doc.course_fee_amount),
			("School", "Public Course", "Public Fee Term", 120))

	def test_public_application_rejects_a_course_outside_the_intake(self):
		from unittest.mock import patch

		import frappe

		from education.education.doctype.student_applicant.student_applicant import StudentApplicant

		register = frappe._dict(admission_based_on="Program", courses=[frappe._dict(course="Allowed")])
		doc = StudentApplicant({"doctype": "Student Applicant", "course": "Other"})
		with patch("education.education.web_form.student_applicant.student_applicant._application_details", return_value=register), self.assertRaises(frappe.ValidationError):
			doc.set_public_admission_details()

	def test_unpublished_intakes_cannot_supply_public_defaults(self):
		from unittest.mock import patch

		import frappe

		from education.education.web_form.student_applicant.student_applicant import _application_details

		with patch.object(frappe, "get_doc", return_value=frappe._dict(docstatus=1, published=0)), self.assertRaises(frappe.ValidationError):
			_application_details("Private Intake")
