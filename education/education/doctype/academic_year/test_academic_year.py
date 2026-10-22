# Copyright (c) 2015, Frappe Technologies and Contributors
# See license.txt


import frappe
from frappe.tests.utils import FrappeTestCase


class TestAcademicYear(FrappeTestCase):
	def test_date_validation(self):
		year = frappe.get_doc(
			{
				"doctype": "Academic Year",
				"academic_year_name": "_Test Academic Year Invalid Dates",
				"company": "_Test Company",
				"year_start_date": "2023-02-13",
				"year_end_date": "2023-01-27",
			}
		)
		self.assertRaises(frappe.ValidationError, year.insert)
