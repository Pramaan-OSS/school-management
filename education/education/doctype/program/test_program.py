# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt


import frappe

from education.education.test_utils import create_program


def make_program(name):
	if not frappe.db.exists("Program", name):
		create_program(name)
	return frappe.get_value("Program", name, "name")


def make_program_and_linked_courses(program_name, course_name_list):
	"""Kept for callers; programs and courses link the other way around now."""
	return make_program(program_name)
