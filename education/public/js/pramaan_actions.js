// Staff and instructor actions that ride the single Pramaan client.
// Every action is an explicit click; results are shown for review.

function toast(message, ok) {
  frappe.msgprint({
    title: ok ? __('Done') : __('Not available'),
    message: message,
    indicator: ok ? 'green' : 'orange',
  });
}

function call(method, args, done) {
  const run = () => frappe.call({
    method: 'education.education.pramaan_features.' + method,
    args: args,
    freeze: true,
    callback: (r) => done(r.message || {}),
  });
  if (['create_class_meeting', 'sync_calendar_entry', 'send_guardian_alerts', 'send_fee_reminder'].includes(method)) {
    frappe.confirm(__('Continue with this action? It may send messages or create entries on connected accounts.'), run);
  } else {
    run();
  }
}

frappe.ui.form.on('Subject Schedule', {
  refresh(frm) {
    frm.add_custom_button(__('Create Online Class'), () => {
      call('create_class_meeting', { subject_schedule: frm.doc.name }, (r) => {
        if (r.url) {
          frappe.msgprint({
            title: __('Online class'),
            message: __('Meeting link:') + ' ' + frappe.utils.escape_html(r.url),
          });
          frm.reload_doc();
        }
      });
    });
    frm.add_custom_button(__('Add to Calendars'), () => {
      call('sync_calendar_entry', { doctype: frm.doc.doctype, name: frm.doc.name }, () => frm.reload_doc());
    });
  },
});

frappe.ui.form.on('Assessment Plan', {
  refresh(frm) {
    frm.add_custom_button(__('Add to Calendars'), () => {
      call('sync_calendar_entry', { doctype: frm.doc.doctype, name: frm.doc.name }, () => frm.reload_doc());
    });
  },
});

frappe.ui.form.on('Student Batch Name', {
  refresh(frm) {
    frm.add_custom_button(__('Notify Guardians of Absences'), () => {
      let d = new frappe.ui.Dialog({
        title: __('Notify Guardians of Absences'),
        fields: [
          { fieldname: 'date', fieldtype: 'Date', label: __('Date'), reqd: 1, default: frappe.datetime.get_today() },
          { fieldname: 'message', fieldtype: 'Small Text', label: __('Message'), reqd: 1 },
          {
            fieldname: 'channel', fieldtype: 'Select', label: __('Channel'),
            options: 'email\nsms', default: 'email',
          },
          { fieldname: 'target_language', fieldtype: 'Data', label: __('Optional: translate into language') },
        ],
        primary_action_label: __('Review and Send'),
        primary_action(values) {
          if (!values.target_language) {
            d.hide();
            call('send_guardian_alerts', {
              student_batch: frm.doc.name, date: values.date,
              message: values.message, channel: values.channel,
            }, (r) => {
              d.hide();
              toast(__('Queued for {0} guardians; {1} students had no available contact.', [r.queued, r.skipped]), true);
            });
            return;
          }
          call('translate_message', { text: values.message, target_language: values.target_language }, (r) => {
            d.set_df_property('message', 'description', __('Original: {0}', [frappe.utils.escape_html(values.message)]));
            d.set_values({ message: r.text || values.message });
            frappe.msgprint({
              title: __('Translation preview'),
              message: frappe.utils.escape_html(r.text || ''),
              indicator: 'blue',
            });
            d.set_primary_action(__('Send'), () => {
              const v = d.get_values();
              d.hide();
              call('send_guardian_alerts', {
                student_batch: frm.doc.name, date: v.date,
                message: v.message, channel: v.channel,
              }, (r2) => toast(__('Queued for {0} guardians; {1} students had no available contact.', [r2.queued, r2.skipped]), true));
            });
          });
        },
      });
      d.show();
    });
  },
});

frappe.ui.form.on('Student Applicant', {
  refresh(frm) {
    if (frm.is_new()) return;
    frm.add_custom_button(__('Prefill From Document'), () => {
      let d = new frappe.ui.Dialog({
        title: __('Prefill From Document'),
        fields: [
          { fieldname: 'file_url', fieldtype: 'Link', label: __('Attached document'),
            options: 'File', get_query: () => ({ filters: { attached_to_doctype: 'Student Applicant', attached_to_name: frm.doc.name } }) },
        ],
        primary_action_label: __('Read document'),
        primary_action(values) {
          d.hide();
          call('prefill_applicant', { applicant: frm.doc.name, file_url: values.file_url }, (r) => {
            const extraction = r.extraction || {};
            const labels = {
              first_name: __('First Name'), last_name: __('Last Name'),
              email_address: __('Email'), student_mobile_number: __('Mobile'),
              address_line_1: __('Address Line 1'), city: __('City'),
              state: __('State'), pincode: __('Pincode'),
            };
            const review = new frappe.ui.Dialog({
              title: __('Review extracted values before using them'),
              fields: [
                { fieldname: 'source', fieldtype: 'HTML', options: '<pre style="white-space:pre-wrap">' + frappe.utils.escape_html(JSON.stringify(extraction, null, 2)) + '</pre>' },
                ...Object.keys(labels).map((key) => ({
                  fieldname: key, fieldtype: 'Data', label: labels[key],
                  default: typeof extraction[key] === 'string' ? extraction[key] : '',
                })),
              ],
              primary_action_label: __('Use reviewed values'),
              primary_action(values) {
                Object.keys(labels).forEach((key) => {
                  if (values[key] && frm.fields_dict[key]) frm.set_value(key, values[key]);
                });
                review.hide();
              },
            });
            review.show();
          });
        },
      });
      d.show();
    });
  },
});

frappe.ui.form.on('Quiz', {
  refresh(frm) {
    frm.add_custom_button(__('Draft Questions'), () => {
      let d = new frappe.ui.Dialog({
        title: __('Draft Questions'),
        fields: [{ fieldname: 'count', fieldtype: 'Int', label: __('How many'), default: 5 }],
        primary_action_label: __('Draft'),
        primary_action(values) {
          d.hide();
          call('draft_quiz_questions', { quiz: frm.doc.name, count: values.count || 5 }, (r) => {
            frappe.msgprint({
              title: __('Review, then edit into the quiz'),
              message: '<pre style="white-space:pre-wrap">' + frappe.utils.escape_html(r.text || '') + '</pre>',
              wide: true,
            });
          });
        },
      });
      d.show();
    });
  },
});

frappe.ui.form.on('Fees', {
  refresh(frm) {
    if (frm.doc.docstatus !== 1) return;
    frm.add_custom_button(__('Send Fee Reminder'), () => {
      call('send_fee_reminder', { fees: frm.doc.name, channel: 'email' }, (r) => {
        toast(r.sent ? __('Reminder accepted for delivery.') : __('The reminder was not accepted for delivery.'), Boolean(r.sent));
      });
    });
  },
});
