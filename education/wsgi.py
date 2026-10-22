"""Production server factory for the bundled local site and assets."""
import os


def create_app():
    import frappe.app

    frappe.app._site = os.environ.get("SCHOOL_SITE_NAME", "school.localhost")
    frappe.app._sites_path = "/app/.runtime/bench/sites"
    return frappe.app.application_with_statics()
