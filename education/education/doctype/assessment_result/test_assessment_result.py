# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from education.education.api import get_grade, get_grade_details
from education.education.test_utils import create_grading_scale


class TestAssessmentResult(FrappeTestCase):
	def test_assessment_report_reads_current_result_fields(self):
		from education.education.report.course_wise_assessment_report.course_wise_assessment_report import (
			get_formatted_result,
		)
		result = get_formatted_result(frappe._dict(academic_year="2023-2024", assessment_group="All Assessment Groups"))
		self.assertIn("assessment_result", result)

	def test_monthly_report_links_to_the_student_doctype(self):
		from education.education.report.student_monthly_attendance_sheet.student_monthly_attendance_sheet import (
			get_columns,
		)
		self.assertEqual(get_columns(31)[0]["options"], "Student")

	def setUp(self):
		create_grading_scale()

	def tearDown(self):
		frappe.db.rollback()

	def test_grade(self):
		grade = get_grade("_Test Grading Scale", 80)
		self.assertEqual("A", grade)

		grade = get_grade("_Test Grading Scale", 70)
		self.assertEqual("B", grade)

	def test_grade_details_include_gpa(self):
		scale_name = "_Test GPA Grading Scale"
		create_grading_scale(scale_name)
		details = get_grade_details(scale_name, 80)
		self.assertEqual("A", details.grade_code)
		self.assertEqual(4.0, details.gpa)
		self.assertEqual(1, details.include_gpa)
		self.assertEqual(1, details.earn_credits)

		failing = get_grade_details(scale_name, 40)
		self.assertEqual("F", failing.grade_code)
		self.assertEqual(0.0, failing.gpa)
		self.assertEqual(0, failing.earn_credits)
