"""Meeting requests use the same identity as hosted app connections."""
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from education.education import pramaan_features as features
from education.pramaan import PramaanClient


class TestConnectionIdentity(TestCase):
    def test_meeting_create_and_read_use_the_connected_user(self):
        calls = []
        def transport(method, url, headers, body):
            calls.append(body)
            return 200, {"ref": "room-fixture", "joinUrl": "https://class.school.test/room", "status": "scheduled"}
        fake = PramaanClient(api_key="fixture-only", transport=transport)
        doc = frappe._dict(name="class-fixture", faculty="local-faculty-record", subject="Math",
            title="Class", schedule_date="2026-10-19", from_time="09:00:00", to_time="10:00:00",
            meeting_room_ref=None, meeting_url=None, check_permission=Mock(), db_set=Mock())
        def action(capability, inputs, **kwargs):
            return fake.call(capability, inputs, idempotency_key="saved-room-intent")
        with patch.object(features, "_staff"), patch.object(frappe, "get_doc", return_value=doc), patch.object(features, "client", return_value=fake), patch.object(features, "_action", side_effect=action), patch.object(frappe.db, "get_single_value", side_effect=lambda doctype, field: "zoom" if field == "meetings_app" else "UTC"):
            features.create_class_meeting("class-fixture")
            doc.meeting_room_ref = "room-fixture"
            features.get_class_meeting("class-fixture")
        expected = features._end_user_ref()
        self.assertEqual([body["endUserRef"] for body in calls], [expected, expected])

    def test_extraction_populates_review_fields_without_saving(self):
        fake = PramaanClient(api_key="fixture-only", transport=lambda *args: (200, {"data": {"first_name": "Live", "city": "Boston"}, "truncated": False}))
        applicant = Mock()
        attachment = frappe._dict(attached_to_doctype="Student Applicant", attached_to_name="applicant-fixture", file_name="form.pdf", get_content=lambda: b"local document", check_permission=Mock())
        with patch.object(features, "_staff"), patch.object(frappe, "get_doc", side_effect=[applicant, attachment]), patch.object(features, "client", return_value=fake):
            result = features.prefill_applicant("applicant-fixture", "attached-file")
        self.assertEqual(result["extraction"]["first_name"], "Live")
        self.assertEqual(result["extraction"]["city"], "Boston")
        applicant.save.assert_not_called()

    def test_non_student_identity_returns_an_explicit_empty_result(self):
        from education.education.api import get_student_info
        with patch.object(frappe.local, "session", frappe._dict(user="Administrator")):
            self.assertIs(get_student_info(), False)
        with patch.object(frappe.local, "session", frappe._dict(user="staff-fixture")), patch.object(frappe.db, "get_list", return_value=[]):
            self.assertIs(get_student_info(), False)

    def test_desktop_keeps_local_tools_without_external_support_links(self):
        from education.overrides.desktop import update_boot
        boot = {"app_data": [{"app_name": "frappe", "app_route": "/desk/build", "app_title": "Original"}],
                "apps_data": {"apps": [{"name": "erpnext", "route": "/desk/home", "title": "Original"}]},
                "navbar_settings": {"help_dropdown": [{"item_label": "About"}, {"item_label": "Support", "route": "https://support.school.test"}, {"item_label": "System Health", "route": "/desk/system-health-report"}]}}
        boot["navbar_settings"] = frappe.get_doc({"doctype": "Navbar Settings", **boot["navbar_settings"]})
        update_boot(boot)
        self.assertEqual(boot["app_data"][0]["app_title"], "Administration")
        self.assertEqual(boot["apps_data"]["apps"][0]["title"], "Accounts")
        self.assertEqual(boot["app_data"][0]["app_route"], "/desk/build")
        self.assertEqual([i["item_label"] for i in boot["navbar_settings"]["help_dropdown"]], ["System Health"])

    def test_checkout_keeps_invoice_cents_and_accepts_email_without_phone(self):
        from education.education import billing
        calls = []
        def transport(method, url, headers, body):
            if url.endswith('payments.account.status'):
                return 200, {"status": "ready", "chargesEnabled": True}
            calls.append((headers, body))
            return 200, {"ref": "checkout-fixture", "checkoutUrl": "https://checkout.school.test/pay"}
        fake = PramaanClient(api_key="fixture-only", transport=transport)
        record = Mock()
        record.name = "local-payment-fixture"
        details = frappe._dict(name="invoice-fixture", student="student-fixture", outstanding_amount=10.75, currency="USD")
        with patch.object(billing, "client", return_value=fake), patch.object(billing, "get_details", return_value=details), patch.object(billing, "_check_permission"), patch.object(frappe, "get_all", return_value=[]), patch.object(frappe, "get_doc", return_value=record):
            result = billing.create_checkout("Sales Invoice", "invoice-fixture", {"email": "payer@school.test"})
        self.assertEqual(calls[0][1]["lineItems"][0]["amount"], 1075)
        self.assertEqual(calls[0][1]["customerEmail"], "payer@school.test")
        self.assertTrue(calls[0][0]["Idempotency-Key"])
        self.assertEqual(result["checkout"], "local-payment-fixture")
        self.assertEqual(billing._minor_units("10.005"), 1001)
        self.assertEqual(billing._minor_units(0.29), 29)
