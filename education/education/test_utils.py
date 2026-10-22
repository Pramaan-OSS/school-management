import frappe
from erpnext.setup.utils import enable_all_roles_and_domains
from frappe.utils import add_years, now_datetime, nowdate

from education.education.doctype.fee_schedule.fee_schedule import get_fee_structure

DEFAULT_PROGRAM_NAME = "Class 1"
DEFAULT_ACADEMIC_YEAR = "2023-2024"
DEFAULT_ACADEMIC_TERM = "2023-2024 (Term 1)"
DEFAULT_STUDENT_BATCH = "Test Batch"
DEFAULT_COURSE = "Test Course"
DEFAULT_FEES_CATEGORY = "Tuition Fee"
DEFAULT_STUDENT_EMAIL_ID = "test@example.com"


def before_tests():
	frappe.clear_cache()
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	year = now_datetime().year
	if not frappe.get_list("Company"):
		setup_complete(
			{
				"currency": "INR",
				"full_name": "Test User",
				"company_name": "_Test Company",
				"timezone": "Asia/Kolkata",
				"company_abbr": "_TC",
				"industry": "Manufacturing",
				"country": "India",
				"fy_start_date": f"{year}-01-01",
				"fy_end_date": f"{year}-12-31",
				"language": "english",
				"company_tagline": "Testing",
				"email": "test@example.com",
				"password": "test",
				"chart_of_accounts": "Standard",
			}
		)

	frappe.db.set_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing", 0)
	enable_all_roles_and_domains()
	make_holiday_list()
	# Site bootstrap must persist before the test suite starts.
	frappe.db.commit()  # nosemgrep


def make_holiday_list(holiday_list_name="Test Holiday List"):
	if not frappe.db.get_value("Holiday List", holiday_list_name):
		holiday_list = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": holiday_list_name,
				"from_date": nowdate(),
				"to_date": add_years(nowdate(), 1),
				"weekly_off": "Sunday",
			}
		).insert()
		holiday_list.get_weekly_off_dates()
		holiday_list.save()


def create_academic_year(
	academic_year_name=DEFAULT_ACADEMIC_YEAR,
	year_start_date=None,
	year_end_date=None,
	company="_Test Company",
):
	if frappe.db.exists("Academic Year", {"academic_year_name": DEFAULT_ACADEMIC_YEAR}):
		return

	academic_year = frappe.new_doc("Academic Year")
	academic_year.academic_year_name = academic_year_name
	academic_year.company = company
	academic_year.year_start_date = year_start_date or "2023-04-01"
	academic_year.year_end_date = year_end_date or "2024-03-31"
	academic_year.save()


def create_academic_term(
	term_start_date, term_end_date, academic_year=DEFAULT_ACADEMIC_YEAR, term_name="Term 1"
):
	if frappe.db.exists("Academic Term", {"term_name": "Term 1"}):
		return

	academic_term = frappe.new_doc("Academic Term")
	academic_term.academic_year = academic_year
	academic_term.company = frappe.db.get_value("Academic Year", academic_year, "company")
	academic_term.term_name = term_name
	academic_term.term_start_date = term_start_date
	academic_term.term_end_date = term_end_date
	academic_term.save()


def create_fee_category(category_name=DEFAULT_FEES_CATEGORY):
	if frappe.db.exists("Fee Category", {"category_name": category_name}):
		return frappe.get_doc("Fee Category", {"category_name": category_name})
	fee_category = frappe.new_doc("Fee Category")
	fee_category.category_name = category_name
	fee_category.save()
	return fee_category


def _receivable_account(company):
	account = frappe.db.get_value("Company", company, "default_receivable_account")
	if not account:
		account = frappe.get_value(
			"Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
		)
	return account


def create_fee_term(fee_term_name="_Test Fee Term"):
	if frappe.db.exists("Fee Term", fee_term_name):
		return fee_term_name
	company = default_company()
	fee_term = frappe.new_doc("Fee Term")
	fee_term.fee_term_name = fee_term_name
	fee_term.term_type = "Fixed Fees of Days"
	fee_term.company = company
	fee_term.receivable_account = _receivable_account(company)
	fee_term.posting_date = nowdate()
	fee_term.append(
		"fee_components",
		{"fees_category": create_fee_category().category_name, "value": 100},
	)
	fee_term.append(
		"payment_terms",
		{"percent_of_total": 100, "due_days": 30, "reminder_days": 1, "reminder_direction": "Before"},
	)
	fee_term.save()
	return fee_term.name


def create_grade_template(template_name="_Test Grade Template"):
	if frappe.db.exists("Grade Template", template_name):
		return template_name
	for name, kind in (("_Test Homework", "Subjective"), ("_Test Exam", "Exam")):
		if not frappe.db.exists("Assignment Type", name):
			frappe.get_doc(
				{"doctype": "Assignment Type", "__newname": name, "assignment_type": kind}
			).insert()
	company = default_company()
	create_academic_year()
	if not frappe.db.exists("Academic Term", DEFAULT_ACADEMIC_TERM):
		create_academic_term("2023-04-01", "2023-09-30")
	template = frappe.new_doc("Grade Template")
	template.template_name = template_name
	template.company = company
	template.academic_year = DEFAULT_ACADEMIC_YEAR
	template.academic_term = DEFAULT_ACADEMIC_TERM
	template.weightage_type = "Assignment Type Weightage"
	template.append("assignment_weights", {"assignment_type": "_Test Homework", "weightage": 40})
	template.append("assignment_weights", {"assignment_type": "_Test Exam", "weightage": 60})
	template.save()
	return template.name


def default_company():
	company = frappe.db.get_value("Company", {"company_name": "_Test Company"}, "name")
	return company or frappe.get_all("Company", pluck="name", limit=1)[0]


def create_area_of_study(area_name="General"):
	if not frappe.db.exists("Area of Study", area_name):
		frappe.get_doc(
			{
				"doctype": "Area of Study",
				"area_name": area_name,
				"abbreviation": area_name[:4].upper(),
				"company": default_company(),
			}
		).insert()
	return area_name


def create_program_level(program_level="Primary"):
	if not frappe.db.exists("Program Level", program_level):
		frappe.get_doc({"doctype": "Program Level", "program_level": program_level}).insert()
	return program_level


def create_program(name=DEFAULT_PROGRAM_NAME):
	if frappe.db.exists("Program", name):
		return
	program = frappe.new_doc("Program")
	program.program_name = name
	program.program_abbreviation = "".join(part[0] for part in name.split() if part).upper() or "PR"
	program.area_of_study = create_area_of_study()
	program.program_level = create_program_level()
	program.company = default_company()
	program.short_description = name
	program.save()


def create_fee_structure(
	academic_year=DEFAULT_ACADEMIC_YEAR,
	academic_term=DEFAULT_ACADEMIC_TERM,
	program=DEFAULT_PROGRAM_NAME,
	components=None,
	submit=False,
):
	fee_structure = frappe.new_doc("Fee Structure")
	fee_structure.academic_year = academic_year or DEFAULT_ACADEMIC_YEAR
	fee_structure.academic_term = academic_term or DEFAULT_ACADEMIC_TERM
	fee_structure.program = program or DEFAULT_PROGRAM_NAME
	fee_structure.company = default_company()
	fee_structure.receivable_account = _receivable_account(fee_structure.company)
	for c in components:
		fee_structure.append(
			"components",
			{
				"fees_category": c.get("fees_category"),
				"amount": c.get("amount"),
				"discount": c.get("discount", 0),
			},
		)
	fee_structure.save()
	if submit:
		fee_structure.submit()
	return fee_structure


def create_student(first_name="Test", last_name="Student", student_email_id=DEFAULT_STUDENT_EMAIL_ID):
	if frappe.db.exists("Student", {"student_email_id": student_email_id}):
		return frappe.get_doc("Student", {"student_email_id": student_email_id})

	student = frappe.new_doc("Student")
	student.first_name = first_name
	student.last_name = last_name
	student.student_email_id = student_email_id
	student.email_address = student_email_id
	student.save()
	return student


def create_student_batch(
	batch_name=DEFAULT_STUDENT_BATCH,
	course=DEFAULT_COURSE,
	start_date="2023-01-01",
	end_date=None,
):
	if frappe.db.exists("Student Batch Name", batch_name):
		return frappe.get_doc("Student Batch Name", batch_name)

	student_batch = frappe.new_doc("Student Batch Name")
	student_batch.batch_name = batch_name
	student_batch.course = course
	student_batch.company = default_company()
	student_batch.start_date = start_date
	student_batch.end_date = end_date or add_years(nowdate(), 1)
	student_batch.save()

	return student_batch


def enroll_student_in_batch(student, course=DEFAULT_COURSE, batch=DEFAULT_STUDENT_BATCH):
	"""Submit the course enrollment that puts the student in the batch."""
	if frappe.db.exists("Course Enrollment", {"student": student, "student_batch": batch}):
		return
	company = default_company()
	register = frappe.db.get_value(
		"Admission Register", {"academic_year": DEFAULT_ACADEMIC_YEAR, "company": company}, "name"
	)
	if not register:
		register_doc = frappe.get_doc(
			{
				"doctype": "Admission Register",
				"__newname": "_Test Admission Register",
				"academic_year": DEFAULT_ACADEMIC_YEAR,
				"admission_based_on": "Course",
				"course": course,
				"course_fee_amount": 1000,
				"start_date": "2023-01-01",
				"end_date": add_years(nowdate(), 1),
				"max_number_of_admissions": 100,
				"minimum_age": 3,
				"company": company,
			}
		).insert()
	else:
		register_doc = frappe.get_doc("Admission Register", register)
	if register_doc.docstatus == 0:
		register_doc.submit()
		register_doc.reload()
	if register_doc.status in {"Draft", "Submitted"}:
		register_doc.publish()
	if register_doc.status != "Admission Open":
		register_doc.start_admission()
	register = register_doc.name
	enrollment = frappe.get_doc(
		{
			"doctype": "Course Enrollment",
			"admission_register": register,
			"student": student,
			"course": course,
			"student_batch": batch,
			"program": DEFAULT_PROGRAM_NAME,
			"enrollment_date": nowdate(),
			"fee_term": create_fee_term(),
			"company": company,
		}
	).insert()
	enrollment.submit()


def create_fee_schedule(academic_year=DEFAULT_ACADEMIC_YEAR, submit=False, fee_structure=None):
	due_date = frappe.utils.add_days(frappe.utils.nowdate(), 2)
	fee_structure_name = fee_structure or frappe.db.get_value(
		"Fee Structure", {"academic_year": academic_year}, "name"
	)
	fee_schedule = frappe.new_doc("Fee Schedule")
	fee_schedule.fee_structure = fee_structure_name
	fee_schedule = get_fee_structure(fee_structure_name)
	fee_schedule.due_date = due_date

	student_batches = frappe.db.get_list("Student Batch Name", {"name": DEFAULT_STUDENT_BATCH}, "name")
	for batch in student_batches:
		fee_schedule.append("student_batches", {"student_batch": batch.get("name")})

	fee_schedule.save()
	if submit:
		fee_schedule.submit()

	return fee_schedule


def create_faculty(first_name="Test", last_name="Faculty", email=None, subjects=None):
	faculty_name = " ".join(name for name in (first_name, last_name) if name)
	existing = frappe.db.exists("Faculty", {"faculty_name": faculty_name})
	if existing:
		return frappe.get_doc("Faculty", existing)

	frappe.db.set_single_value("Education Settings", "user_creation_skip", 1)
	faculty = frappe.new_doc("Faculty")
	faculty.first_name = first_name
	faculty.last_name = last_name
	faculty.naming_series = "EDU-FCT-.YYYY.-"
	faculty.email_address = email or f"{first_name.lower()}.{last_name.lower().replace(' ', '')}@example.com"
	faculty.insert(ignore_mandatory=True)
	for subject in subjects or []:
		if frappe.db.exists("Subject", subject):
			faculty.append("subjects", {"subject": subject})
	if faculty.subjects:
		faculty.save()
	return faculty


def create_subject(subject_name="Test Subject", course=DEFAULT_COURSE):
	if frappe.db.exists("Subject", subject_name):
		return frappe.get_doc("Subject", subject_name)

	subject = frappe.new_doc("Subject")
	subject.subject_name = subject_name
	subject.abbreviation = "".join(part[0] for part in subject_name.split() if part).upper() or "SUB"
	subject.type = "Theory"
	subject.subject_type = "Compulsory"
	subject.course = course
	subject.save()
	return subject


def create_instructor(instructor_name="Test Instructor"):
	if not frappe.db.exists("Instructor", {"instructor_name": instructor_name}):
		instructor = frappe.new_doc("Instructor")
		instructor.instructor_name = instructor_name
		instructor.save()


def create_course(course_name="Test Course"):
	if not frappe.db.exists("Course", {"course_name": course_name}):
		course = frappe.new_doc("Course")
		course.course_name = course_name
		course.course_abbreviation = "".join(part[0] for part in course_name.split() if part).upper() or "TC"
		course.evaluation_type = "Normal"
		course.company = default_company()
		course.short_description = course_name
		course.default_grading_scale = create_grading_scale()
		course.fee_term = create_fee_term()
		course.append("grade_templates", {"grade_template": create_grade_template()})
		course.save()


def create_room(room_name="Test Room"):
	if not frappe.db.exists("Room", {"room_name": room_name}):
		room = frappe.new_doc("Room")
		room.room_name = room_name
		room.save()


def create_grading_scale(grading_scale_name="_Test Grading Scale"):
	if frappe.db.exists("Grading Scale", grading_scale_name):
		return grading_scale_name

	company = frappe.db.get_value(
		"Company", {"company_name": "_Test Company"}, "name"
	) or frappe.db.get_value("Company", {}, "name")

	grading_scale = frappe.new_doc("Grading Scale")
	grading_scale.grading_scale_name = grading_scale_name
	if company:
		grading_scale.company = company
	grades = {
		"A": (80, 100, 4.0, 1, 1),
		"B": (70, 79, 3.0, 1, 1),
		"C": (60, 69, 2.0, 1, 1),
		"D": (50, 59, 1.0, 1, 1),
		"F": (0, 49, 0.0, 1, 0),
	}
	for grade, (minimum, maximum, gpa, include_gpa, earn_credits) in grades.items():
		grading_scale.append(
			"intervals",
			{
				"grade_code": grade,
				"minimum_percentage": minimum,
				"maximum_percentage": maximum,
				"gpa": gpa,
				"include_gpa": include_gpa,
				"earn_credits": earn_credits,
			},
		)

	grading_scale.save()
	grading_scale.submit()
	return grading_scale.name


def create_company(company_name):
	company = frappe.get_doc({"doctype": "Company", "company_name": company_name, "default_currency": "INR"})
	company.insert(ignore_if_duplicate=True)


def get_defaults(company_name="_Test Company"):
	defaults = frappe.get_all(
		"Company",
		filters={"name": company_name},
		fields=["default_income_account", "cost_center"],
		limit=1,
	)[0]
	return defaults
