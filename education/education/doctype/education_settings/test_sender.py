"""Outgoing mail always uses the single school sender setting."""
from unittest.mock import patch
import frappe
from unittest import TestCase
from education.integrations.pramaan_mail import sender_account


class TestSchoolSender(TestCase):
    def test_default_sender_keeps_the_display_name(self):
        expected = frappe.get_meta("Education Settings").get_field("pramaan_sender").default
        with patch.object(frappe.db, "get_single_value", return_value=None):
            self.assertEqual(sender_account(), expected)

    def test_one_setting_overrides_framework_sender_arguments(self):
        configured = "School Office <notifications@school.test>"
        with patch.object(frappe.db, "get_single_value", return_value=configured):
            self.assertEqual(sender_account("Administrator <ignored@school.test>"), configured)

    def test_multiple_sender_addresses_are_rejected(self):
        with patch.object(frappe.db, "get_single_value", return_value="one@school.test, two@school.test"):
            with self.assertRaises(frappe.ValidationError):
                sender_account()

    def test_delivery_does_not_vouch_for_a_local_user_as_a_platform_member(self):
        import json
        from unittest.mock import Mock
        from education.pramaan import PramaanClient
        from education.integrations import pramaan_mail

        headers = {}
        def transport(method, url, sent_headers, body):
            headers.update(sent_headers)
            return 200, {"status": "sent", "ref": "mail-fixture"}
        fake = PramaanClient(api_key="fixture-only", transport=transport)
        outbox = Mock(state="Pending", capability="email.send", payload=json.dumps({
            "from": "School <sender@school.test>", "to": ["recipient@school.test"],
            "subject": "School notice", "text": "Fixture"}),
            idempotency_key="saved-mail-intent", requested_by="Administrator", communication=None)
        with patch.object(pramaan_mail, "client", return_value=fake), patch.object(frappe, "get_doc", return_value=outbox), patch.object(frappe.db, "sql"), patch.object(frappe.db, "commit"), patch.object(pramaan_mail, "finish_legacy_queue"):
            pramaan_mail.deliver("mail-fixture")
        self.assertEqual(headers["Idempotency-Key"], "saved-mail-intent")
        self.assertNotIn("Pramaan-Approved-By", headers)
