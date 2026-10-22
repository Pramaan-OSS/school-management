// Mail accounts store owned sender addresses; delivery uses the shared client.
frappe.ui.form.on('Email Account', {
  refresh(frm) {
    frm.clear_custom_buttons();
    const visible = new Set(['email_account_name', 'email_id', 'enable_outgoing', 'default_outgoing', 'always_use_account_email_id_as_sender', 'always_use_account_name_as_sender_name']);
    for (const field of frm.meta.fields) {
      if (!['Section Break', 'Column Break', 'Tab Break'].includes(field.fieldtype)) frm.toggle_display(field.fieldname, visible.has(field.fieldname));
    }
    frm.$wrapper.find('.section-head, .section-description').hide();
    // Keep the sections containing the supported address fields visible.
    for (const field of visible) if (frm.fields_dict[field]?.section) $(frm.fields_dict[field].section.wrapper).show();
    frm.set_intro(__('Messages use Pramaan. Save an address you own and enable outgoing mail. Incoming mail is unavailable here.'));
  },
});
