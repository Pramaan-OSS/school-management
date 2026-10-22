# Copyright (c) 2015, Frappe Technologies and Contributors
# See license.txt


import frappe

from education.education.doctype.program.test_program import (
	make_program_and_linked_courses,
)

test_records = frappe.get_test_records("Student")
from frappe.tests.utils import FrappeTestCase

from education.education.test_utils import create_student


class TestStudent(FrappeTestCase):
	def setUp(self):
		create_student()

	def test_create_student_user(self):
		self.assertTrue(bool(frappe.db.exists("User", "test@example.com")))

	def test_create_customer_against_student(self):
		student = frappe.get_doc("Student", {"student_email_id": "test@example.com"})
		self.assertTrue(bool(student.customer))
		self.assertEqual(student.customer_group, "Student")

	def test_new_student_can_be_edited_without_reloading(self):
		frappe.db.set_single_value("Education Settings", "user_creation_skip", 1)
		student = create_student("QA", "Editable", "editable-qa@example.com")
		self.assertTrue(student.customer)
		student.middle_name = "Updated"
		student.save()
		self.assertEqual(frappe.db.get_value("Student", student.name, "middle_name"), "Updated")

	def tearDown(self):
		frappe.db.rollback()


class TestPortalContracts(FrappeTestCase):
	def test_unlinked_user_has_no_student_profile(self):
		from unittest.mock import patch
		from education.education.api import get_student_info
		with patch.dict(frappe.session, {'user': 'unlinked@example.com'}), patch.object(frappe.db, 'get_list', return_value=[]):
			self.assertIsNone(get_student_info())

	def test_student_cannot_read_another_students_grades(self):
		from unittest.mock import patch
		from education.education.api import get_student_grades
		with patch.dict(frappe.session, {'user': 'student@example.com'}), patch.object(frappe, 'get_roles', return_value=['Student']), patch.object(frappe.db, 'exists', return_value=None):
			with self.assertRaises(frappe.PermissionError):
				get_student_grades('another-student')
