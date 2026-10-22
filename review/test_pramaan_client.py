"""Standalone contract checks for the single Pramaan client (no live calls)."""
import os
import unittest
from unittest import mock

# The client module imports frappe only inside app modules; keep this pure.
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "education_pramaan", Path(__file__).resolve().parents[1] / "education" / "pramaan.py"
)
pramaan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pramaan)


def ok(method, url, headers, body):
    return 200, {"status": "queued"}


class ClientTests(unittest.TestCase):
    def make(self, transport=ok, key="test-key", env=None):
        with mock.patch.dict(os.environ, env or {}, clear=False):
            os.environ.pop("PRAMAAN_FAKE", None)
            return pramaan.PramaanClient(api_key=key, transport=transport)

    def test_unsupported_capability_is_refused(self):
        with self.assertRaises(pramaan.PramaanError) as ctx:
            self.make().run("web.search", {})
        self.assertEqual(ctx.exception.code, "unsupported_capability")

    def test_action_requires_idempotency_key(self):
        with self.assertRaises(pramaan.PramaanError) as ctx:
            self.make().run("email.send", {"to": ["a@b.c"]})
        self.assertEqual(ctx.exception.code, "missing_idempotency_key")

    def test_account_connection_is_an_action(self):
        with self.assertRaises(pramaan.PramaanError) as ctx:
            self.make().run("payments.account.connect", {"returnUrl": "http://localhost:3037"})
        self.assertEqual(ctx.exception.code, "missing_idempotency_key")

    def test_action_with_key_passes_headers(self):
        seen = {}

        def transport(method, url, headers, body):
            seen.update(headers=headers, url=url, body=body)
            return 200, {"paymentLinkId": "pl_1", "paymentUrl": "https://pay.example/pl_1"}

        client = self.make(transport)
        result = client.run("payments.payment-link.create", {"amount": 1000, "currency": "USD"},
                            idempotency_key="abc", approved_by="user@example.com")
        self.assertEqual(result["paymentUrl"], "https://pay.example/pl_1")
        self.assertEqual(seen["headers"]["Idempotency-Key"], "abc")
        self.assertEqual(seen["headers"]["Pramaan-Approved-By"], "user@example.com")
        self.assertTrue(seen["url"].endswith("/v1/capabilities/payments.payment-link.create"))

    def test_school_tax_category_is_sent_on_estimate_and_link_creation(self):
        seen = []
        def transport(method, url, headers, body):
            seen.append((url, headers, body))
            if url.endswith('/estimate'):
                return 200, {"can_run": True, "price_max_micro": 0}
            return 200, {"paymentUrl": "https://pay.school.test/fee"}
        client = self.make(transport, env={"PRAMAAN_TAX_CATEGORY": ""})
        inputs = {"amount": 1075, "currency": "USD"}
        client.estimate("payments.payment-link.create", inputs)
        client.run("payments.payment-link.create", inputs, idempotency_key="fee-tax-fixture")
        self.assertEqual([row[2]["taxCategory"] for row in seen], ["edtech", "edtech"])
        self.assertEqual(inputs, {"amount": 1075, "currency": "USD"})
        self.assertEqual(seen[1][1]["Idempotency-Key"], "fee-tax-fixture")
        self.assertTrue(all("Pramaan-Account" not in row[1] for row in seen))

    def test_tax_category_uses_one_configured_setting(self):
        seen = []
        client = self.make(lambda method, url, headers, body: (seen.append(body) or 200, {"status": "queued"}),
                           env={"PRAMAAN_TAX_CATEGORY": " saas "})
        client.run("payments.payment-link.create", {"amount": 1000, "currency": "USD", "taxCategory": "caller-value"}, idempotency_key="fee-category")
        self.assertEqual(seen[0]["taxCategory"], "saas")

    def test_tax_category_does_not_change_other_capabilities(self):
        seen = []
        client = self.make(lambda method, url, headers, body: (seen.append(body) or 200, {"status": "queued"}))
        client.run("email.send", {"subject": "Fixture"}, idempotency_key="mail-category")
        self.assertNotIn("taxCategory", seen[0])

    def test_missing_key_is_a_plain_message(self):
        client = self.make(key="  ")
        with self.assertRaises(pramaan.MissingPramaanKey) as ctx:
            client.run("email.send", {"to": ["a@b.c"]}, idempotency_key="k")
        self.assertEqual(str(ctx.exception), pramaan.MISSING_KEY_MESSAGE)

    def test_unavailable_capability_raises_plain_surface(self):
        def transport(method, url, headers, body):
            return 503, {"error": {"code": "upstream_unavailable"}}

        with self.assertRaises(pramaan.PramaanNotAvailable) as ctx:
            self.make(transport).run("payments.checkout.create", {}, idempotency_key="k")
        self.assertIn("not available yet", str(ctx.exception))

    def test_upstream_unavailable_is_plain_everywhere(self):
        def transport(method, url, headers, body):
            return 502, {"error": {"code": "upstream_unavailable", "retryable": False,
                                   "message": "provider detail token=xyz"}}

        for capability in ("meetings.room.create", "sms.send", "text.translate", "llm.complete"):
            with self.assertRaises(pramaan.PramaanNotAvailable) as ctx:
                self.make(transport).run(capability, {"messages": [{"role": "user", "content": "x"}]}
                                          if capability == "llm.complete" else {},
                                         idempotency_key="k" if capability != "text.translate" else None)
            self.assertIn("not available yet", str(ctx.exception))
            self.assertFalse(ctx.exception.uncertain)
            self.assertNotIn("token", str(ctx.exception))

    def test_connection_required_is_plain(self):
        def transport(method, url, headers, body):
            return 409, {"error": {"code": "connection_required", "slot": "meetings",
                                   "message": "connect your provider-thing token=xyz"}}

        with self.assertRaises(pramaan.ConnectionRequired) as ctx:
            self.make(transport).run("meetings.room.create", {"title": "class"},
                                     idempotency_key="k", approved_by="user@example.com")
        self.assertIn("meetings", str(ctx.exception))
        self.assertIn("Connect the", str(ctx.exception))
        self.assertNotIn("provider-thing", str(ctx.exception))
        self.assertNotIn("token", str(ctx.exception))
        self.assertFalse(ctx.exception.uncertain)

    def test_estimate_connection_required_is_plain(self):
        def transport(method, url, headers, body):
            self.assertTrue(url.endswith("/estimate"))
            return 200, {"price_max_micro": 0, "balance_micro": 500, "can_run": False,
                         "reason": "connection_required", "slot": "payments"}

        with self.assertRaises(pramaan.ConnectionRequired) as ctx:
            self.make(transport).estimate("payments.checkout.create", {"amount": 100})
        self.assertIn("payments", str(ctx.exception))

    def test_estimate_runs_when_allowed(self):
        def transport(method, url, headers, body):
            return 200, {"price_max_micro": 100, "balance_micro": 500, "can_run": True}

        result = self.make(transport).estimate("payments.checkout.create", {"amount": 100})
        self.assertTrue(result["can_run"])

    def test_estimate_slot_is_only_a_plain_family_name(self):
        def transport(method, url, headers, body):
            return 200, {"price_max_micro": 0, "balance_micro": 500, "can_run": False,
                         "reason": "connection_required", "slot": "Acme Corp <script>"}

        with self.assertRaises(pramaan.ConnectionRequired) as ctx:
            self.make(transport).estimate("meetings.room.create", {"title": "class"})
        self.assertNotIn("Acme", str(ctx.exception))
        self.assertIn("online meetings", str(ctx.exception))

    def test_server_failure_on_post_is_uncertain(self):
        def transport(method, url, headers, body):
            return 502, {"error": {"code": "bad_gateway"}}

        with self.assertRaises(pramaan.PramaanError) as ctx:
            self.make(transport).run("email.send", {"to": ["a@b.c"]}, idempotency_key="k")
        self.assertTrue(ctx.exception.uncertain)

    def test_upstream_body_is_never_surfaced(self):
        def transport(method, url, headers, body):
            return 400, {"error": {"code": "invalid_request", "message": "secret detail token=xyz"}}

        with self.assertRaises(pramaan.PramaanError) as ctx:
            self.make(transport).run("email.send", {"to": ["a@b.c"]}, idempotency_key="k")
        self.assertNotIn("token=xyz", str(ctx.exception))

    def test_read_status_call(self):
        def transport(method, url, headers, body):
            self.assertEqual(method, "POST")
            return 200, {"status": "ready", "chargesEnabled": True, "payoutsEnabled": True,
                         "detailsSubmitted": True, "requirementsDue": []}

        self.assertTrue(self.make(transport).payment_account_ready())

    def test_job_polling_completes(self):
        polls = {"n": 0}

        def transport(method, url, headers, body):
            if method == "POST":
                return 202, {"job_id": "j1", "status": "running"}
            polls["n"] += 1
            state = "done" if polls["n"] > 1 else "running"
            result = {"status": state}
            if state == "done":
                result["result"] = {"status": "queued"}
            return 200, result

        client = self.make(transport)
        client._sleep = lambda _: None
        self.assertEqual(client.call("email.send", {"to": ["a@b.c"]}, idempotency_key="k"), {"status": "queued"})

    def test_fixture_mode_has_no_outside_success(self):
        fake = pramaan.PramaanClient(api_key="k", transport=pramaan.PramaanClient._fake)
        status, body = pramaan.PramaanClient._fake(
            "POST", "https://api.pramaan.dev/v1/capabilities/payments.account.status", {}, {})
        self.assertEqual(status, 200)
        self.assertFalse(body["chargesEnabled"])
        status, body = pramaan.PramaanClient._fake(
            "POST", "https://api.pramaan.dev/v1/capabilities/email.send", {}, {})
        self.assertEqual(status, 503)

    def test_generation_requires_messages(self):
        client = self.make()
        with self.assertRaises(pramaan.PramaanError):
            client.run("llm.complete", {"prompt": "hi"})
        with self.assertRaises(pramaan.PramaanError):
            client.run("llm.complete", {"messages": [{"role": "user", "content": "  "}]})
        with self.assertRaises(pramaan.PramaanError):
            client.run("llm.complete", {"messages": [{"role": "user", "content": "x"}], "jsonSchema": {}})

    def test_generation_token_bounds(self):
        seen = {}

        def transport(method, url, headers, body):
            seen.update(body=body)
            return 200, {"text": "1. Q? A. 2"}

        client = self.make(transport)
        client.run("llm.complete", {"messages": [{"role": "user", "content": "draft"}]})
        self.assertEqual(seen["body"]["maxTokens"], pramaan.DEFAULT_GENERATION_TOKENS)
        with self.assertRaises(pramaan.PramaanError):
            client.run("llm.complete", {"messages": [{"role": "user", "content": "draft"}], "maxTokens": 32})

    def test_generation_length_is_incomplete(self):
        def transport(method, url, headers, body):
            return 200, {"text": "partial", "finishReason": "length"}

        with self.assertRaises(pramaan.IncompleteGeneration):
            self.make(transport).run("llm.complete", {"messages": [{"role": "user", "content": "draft"}]})

    def test_sms_is_an_action_and_readonly_calls_pass(self):
        with self.assertRaises(pramaan.PramaanError) as ctx:
            self.make().run("sms.send", {"to": "+15550001111", "body": "hi"})
        self.assertEqual(ctx.exception.code, "missing_idempotency_key")

        def transport(method, url, headers, body):
            self.assertEqual(body, {"text": "hi", "targetLanguage": "fr"})
            return 200, {"text": "bonjour"}

        result = self.make(transport).call("text.translate", {"text": "hi", "targetLanguage": "fr"})
        self.assertEqual(result["text"], "bonjour")

    def test_invalid_base_url_is_refused(self):
        with self.assertRaises(pramaan.PramaanError):
            pramaan.PramaanClient(api_key="k", base_url="https://user:pass@api.pramaan.dev", transport=ok)
        with self.assertRaises(pramaan.PramaanError):
            pramaan.PramaanClient(api_key="k", base_url="ftp://api.pramaan.dev", transport=ok)


if __name__ == "__main__":
    unittest.main()
