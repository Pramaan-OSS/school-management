frappe.ui.form.on('Connected App', {
  refresh(frm) {
    frm.clear_custom_buttons();
    const visible = new Set(['provider_name', 'pramaan_app_id']);
    for (const field of frm.meta.fields) {
      if (!['Section Break', 'Column Break', 'Tab Break'].includes(field.fieldtype)) frm.toggle_display(field.fieldname, visible.has(field.fieldname));
    }
    frm.$wrapper.find('.section-head, .section-description').hide();
    for (const field of visible) if (frm.fields_dict[field]?.section) $(frm.fields_dict[field].section.wrapper).show();
    frm.set_df_property('provider_name', 'label', __('Connection Name'));
    frm.set_intro(__('Choose an application from the Pramaan app catalogue, save, then connect.'));
    if (frm.is_new()) return;
    frm.add_custom_button(__('Connect Application'), () => frappe.call({
      method: 'education.education.pramaan_features.start_app_connection',
      args: { connection: frm.doc.name }, freeze: true,
      callback(r) { if (r.message?.connectUrl) window.location.assign(r.message.connectUrl); },
    }));
  },
});
