"""Use school labels for the bundled local administration screens."""


def update_boot(bootinfo):
    logo = "/assets/education/images/app.svg"
    titles = {"frappe": "Administration", "erpnext": "Accounts", "education": "School Management"}
    for app in bootinfo.get("app_data", []):
        if app.get("app_name") in titles:
            app["app_title"] = titles[app["app_name"]]
            app["app_logo_url"] = logo
    for app in (bootinfo.get("apps_data") or {}).get("apps", []):
        if app.get("name") in titles:
            app["title"] = titles[app["name"]]
            app["logo"] = logo
    navbar = bootinfo.get("navbar_settings") or {}
    if hasattr(navbar, "as_dict"):
        navbar = navbar.as_dict()
        bootinfo["navbar_settings"] = navbar
    for field in ("help_dropdown", "settings_dropdown"):
        navbar[field] = [item for item in navbar.get(field, [])
                         if item.get("item_label") != "About"
                         and not (item.get("route") or "").startswith(("https://", "http://"))]


def configure_navigation():
    """The framework reloads this document after constructing the boot payload."""
    import frappe
    navbar = frappe.get_single("Navbar Settings")
    boot = {"navbar_settings": navbar}
    update_boot(boot)
    for field in ("help_dropdown", "settings_dropdown"):
        navbar.set(field, boot["navbar_settings"][field])
    navbar.save(ignore_permissions=True)
