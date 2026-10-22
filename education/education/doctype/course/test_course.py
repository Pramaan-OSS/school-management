# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt


import frappe

from education.education.test_utils import create_course


def make_course(name):
	if not frappe.db.exists("Course", {"course_name": name}):
		create_course(name)
	return frappe.get_value("Course", {"course_name": name}, "name")
