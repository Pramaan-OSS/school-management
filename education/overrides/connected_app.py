"""Local connection labels with hosted authorization through Pramaan."""
import re

import frappe
from frappe import _
from frappe.integrations.doctype.connected_app.connected_app import ConnectedApp


class SchoolConnectedApp(ConnectedApp):
    def validate(self):
        if self.pramaan_app_id and not re.fullmatch(r"[a-z0-9_-]{1,64}", self.pramaan_app_id):
            frappe.throw(_("Choose an application ID from the app catalogue."))
        for field in ("client_id", "client_secret", "authorization_uri", "token_uri",
                      "userinfo_uri", "introspection_uri", "revocation_uri", "openid_configuration"):
            if self.meta.has_field(field):
                self.set(field, None)

    @frappe.whitelist()
    def initiate_web_application_flow(self):
        from education.education.pramaan_features import start_app_connection
        return start_app_connection(self.name)["connectUrl"]

    @frappe.whitelist()
    def get_openid_configuration(self):
        frappe.throw(_("Use Connect Application to authorize this connection."))
