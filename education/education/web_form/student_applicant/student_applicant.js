frappe.ready(async () => {
  const response = await frappe.call({
    method: 'education.education.web_form.student_applicant.student_applicant.get_application_options',
  })
  const options = response.message || []
  const form = frappe.web_form
  const requested = new URLSearchParams(window.location.search).get('admission_register')
  form.set_df_property('admission_register', 'options', [''].concat(options.map(row => row.name)).join('\n'))
  const choose = async value => {
    const courses = options.find(row => row.name === value)?.courses || []
    form.set_df_property('course', 'options', [''].concat(courses).join('\n'))
    await form.set_value('course', courses.length === 1 ? courses[0] : '')
  }
  form.on('admission_register', (field, value) => choose(value))
  const selected = options.some(row => row.name === requested) ? requested : (options.length === 1 ? options[0].name : '')
  if (selected) { await form.set_value('admission_register', selected); await choose(selected) }
  if (!options.length) frappe.msgprint(__('No admissions are open right now.'))
})
