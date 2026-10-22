frappe.ui.form.on('Education Settings', {
  refresh(frm) {
    if (!frappe.user.has_role('System Manager')) return;
    frm.add_custom_button(__('Payments account'), () => frappe.set_route('payments-account'));
  },
});
