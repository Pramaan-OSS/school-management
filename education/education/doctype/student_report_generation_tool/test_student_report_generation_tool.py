# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt


from frappe.tests.utils import FrappeTestCase


class TestStudentReportGenerationTool(FrappeTestCase):
	pass

	def test_attendance_summary_uses_supported_aggregation(self):
		import frappe
		from education.education.doctype.student_report_generation_tool.student_report_generation_tool import get_attendance_count
		from education.education.test_utils import create_academic_year
		create_academic_year()
		result = get_attendance_count('missing-qa-student', '2023-2024')
		self.assertEqual(result.total, 0)
