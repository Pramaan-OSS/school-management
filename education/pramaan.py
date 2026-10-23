"""All outside service calls go through this server-side module."""

import json
import os
import time
from dataclasses import dataclass
from typing import ClassVar, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

Feature = Literal["fee_payments", "email_delivery"]


class CapabilityUnavailable(RuntimeError):
    """A stable application error safe to show without request data or secrets."""

    code = "capability_unavailable"

    def __init__(self, feature: Feature):
        self.feature = feature
        messages = {
            "fee_payments": "Fee payments are not available yet.",
            "email_delivery": "Email delivery is not available yet.",
        }
        super().__init__(messages[feature])


@dataclass(frozen=True)
class FeatureAvailability:
    feature: Feature
    enabled: bool
    reason: str


class PramaanError(RuntimeError):
    """Normalized error: never expose an upstream body, provider or secret."""

    def __init__(self, code="unavailable", *, uncertain=False, job_id=None):
        self.code = code
        self.uncertain = uncertain
        self.job_id = job_id
        super().__init__(
            "The action may already have completed. Check its status before trying again."
            if uncertain else "Pramaan could not complete this request."
        )


MISSING_KEY_MESSAGE = "Add PRAMAAN_API_KEY to .env"


class MissingPramaanKey(PramaanError):
    http_status_code = 422

    def __init__(self):
        super().__init__("missing_api_key")
        self.args = (MISSING_KEY_MESSAGE,)


SURFACES = (
	("apps.", "App connections"),
    ("payments.", "Fee payments"), ("sms.", "Text messages"),
    ("meetings.", "Online meetings"), ("calendar.", "Calendar entries"),
    ("text.", "Translation"), ("document.", "Document reading"),
    ("llm.", "Drafting help"), ("notify.", "Notifications"),
    ("email.", "Email delivery"),
)


def surface_label(capability):
    return next((label for prefix, label in SURFACES if str(capability or "").startswith(prefix)),
                "This feature")


def plain_slot(slot):
    """Slots are family names (payments, email, meetings); never echo anything else."""
    return isinstance(slot, str) and 2 <= len(slot) <= 24 and slot == slot.lower() \
        and all(character.isalpha() or character in " -" for character in slot)


class PramaanNotAvailable(PramaanError):
    http_status_code = 503

    def __init__(self, capability):
        super().__init__("not_available_yet")
        surface = surface_label(capability)
        self.args = (f"{surface} are not available yet." if surface.endswith("s") and not surface.endswith("ss")
                     else f"{surface} is not available yet.",)


class ConnectionRequired(PramaanError):
    """The capability needs a connected account first; the slot is a family name."""

    http_status_code = 409

    def __init__(self, capability, slot=None):
        super().__init__("connection_required")
        surface = slot if plain_slot(slot) else surface_label(capability).lower()
        self.slot = surface
        self.args = (f"Connect the {surface} account first, then try again.",)


class IncompleteGeneration(PramaanError):
    http_status_code = 422

    def __init__(self):
        super().__init__("incomplete_reply")
        self.args = ("The draft is incomplete because it reached the reply limit. Retry with a larger reply limit.",)


DEFAULT_GENERATION_TOKENS = 256
MINIMUM_GENERATION_TOKENS = 64


def generation_request(inputs):
    """One boundary for generation messages and token limits."""
    if not isinstance(inputs, dict) or "prompt" in inputs or not isinstance(inputs.get("messages"), list) or not inputs["messages"]:
        raise PramaanError("invalid_generation_request")
    for _index, message in enumerate(inputs["messages"]):
        if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant"} \
                or not isinstance(message.get("content"), str) or not message["content"].strip():
            raise PramaanError("invalid_generation_request")
    if "jsonSchema" in inputs or "tools" in inputs:
        raise PramaanError("invalid_generation_request")
    request = {key: value for key, value in inputs.items() if key != "maxTokens"}
    maximum = inputs.get("maxTokens", DEFAULT_GENERATION_TOKENS)
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < MINIMUM_GENERATION_TOKENS:
        raise PramaanError("invalid_generation_request")
    request["maxTokens"] = maximum
    return request


def generation_result(capability, inputs, result):
    if capability == "llm.complete" and isinstance(result, dict) and result.get("finishReason") == "length":
        raise IncompleteGeneration()
    return result


UNAVAILABLE_CODES = frozenset({"upstream_unavailable", "not_available_yet", "not_available",
    "capability_unavailable", "not_implemented", "unsupported_capability"})
KEPT_ERROR_CODES = UNAVAILABLE_CODES | {"connection_required", "forbidden", "approval_required"}


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PramaanClient:
    """Single server-side HTTP client. Mutating requests are never retried."""

    CAPABILITIES = frozenset({
        "payments.transfer-request.create", "payments.transfer-request.get",
        "payments.transfer-request.list", "payments.transfer-request.cancel",
		"apps.connection.start",
        "email.send", "email.status",
        "payments.account.session.create",
        "payments.account.status",
        "payments.account.connect",
        "payments.checkout.create", "payments.checkout.get",
        "payments.payment.get",
        "payments.payment-link.create", "payments.payment-link.get",
        "payments.payment-link.notify",
        "sms.send",
        "meetings.room.create", "meetings.room.get",
        "calendar.event.create", "calendar.event.update",
        "text.translate", "document.extract", "llm.complete",
    })
    ACTIONS = frozenset({
        "payments.account.session.create",
        "payments.transfer-request.create", "payments.transfer-request.cancel",
        "apps.connection.start",
        "email.send",
        "payments.account.connect",
        "payments.checkout.create",
        "payments.payment-link.create",
        "payments.payment-link.notify",
        "sms.send",
        "meetings.room.create",
        "calendar.event.create", "calendar.event.update",
    })

    def __init__(self, *, api_key=None, base_url=None, transport=None, sleep=time.sleep):
        self._api_key = api_key if api_key is not None else os.environ.get("PRAMAAN_API_KEY", "")
        self._tax_category = (os.environ.get("PRAMAAN_TAX_CATEGORY") or "").strip() or "edtech"
        self._base_url = (base_url or os.environ.get("PRAMAAN_BASE_URL") or "https://api.pramaan.dev").rstrip("/")
        parsed = urlparse(self._base_url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "fake-pramaan"}
        ):
            raise PramaanError("invalid_configuration")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise PramaanError("invalid_configuration")
        self._transport = transport or (self._fake if os.environ.get("PRAMAAN_FAKE") == "1" else self._http)
        self._sleep = sleep

    @property
    def configured(self):
        return bool(self._api_key.strip())

    def require_configured(self):
        if not self.configured:
            raise MissingPramaanKey()

    @staticmethod
    def _fake(method, url, headers, body):
        # Explicit local fixture mode has no network transport or outside effects.
        if method == "POST" and urlparse(url).path == "/v1/capabilities/payments.account.status":
            return 200, {"status": "pending", "chargesEnabled": False, "payoutsEnabled": False,
                         "detailsSubmitted": False, "requirementsDue": ["onboarding"]}
        return 503, {"error": {"code": "upstream_unavailable", "retryable": False}}

    def _http(self, method, url, headers, body):
        request = Request(url, data=json.dumps(body).encode() if body is not None else None,
                          headers=headers, method=method)
        try:
            with build_opener(NoRedirects()).open(request, timeout=30) as response:
                raw = response.read(16_000_001)
                if len(raw) > 16_000_000:
                    raise PramaanError("invalid_response")
                return response.status, json.loads(raw)
        except HTTPError as error:
            # Read only bounded, recognized error codes; never surface the upstream body.
            try:
                payload = json.loads(error.read(16_001))
            except (ValueError, OSError):
                payload = None
            error_object = payload.get("error") if isinstance(payload, dict) else None
            code = error_object.get("code") if isinstance(error_object, dict) else None
            if not code and isinstance(payload, dict):
                code = payload.get("code")
            if not isinstance(code, str) or code not in KEPT_ERROR_CODES:
                code = None
            slot = error_object.get("slot") if isinstance(error_object, dict) else None
            result = {"error": code}
            if code == "connection_required" and plain_slot(slot):
                result["slot"] = slot
            return error.code, result
        except (URLError, OSError, ValueError):
            raise PramaanError("unavailable", uncertain=method == "POST") from None

    def _request(self, method, path, body=None, *, idempotency_key=None, approved_by=None,
                 capability=None):
        self.require_configured()
        if capability == "payments.payment-link.create" and body is not None:
            body = {**body, "taxCategory": self._tax_category}
        headers = {"Authorization": "Bearer " + self._api_key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if approved_by:
            headers["Pramaan-Approved-By"] = approved_by
        try:
            status, result = self._transport(method, self._base_url + path, headers, body)
        except PramaanError:
            raise
        except Exception:
            raise PramaanError("unavailable", uncertain=method == "POST") from None
        if status >= 400:
            remote_code = result.get("error") if isinstance(result, dict) else None
            remote_slot = None
            if isinstance(remote_code, dict):
                remote_slot = remote_code.get("slot")
                remote_code = remote_code.get("code")
            if not remote_code and isinstance(result, dict):
                remote_code = result.get("code")
            if remote_code == "upstream_unavailable":
                # The plain not-available-yet answer; nothing ran, so it is never uncertain.
                raise PramaanNotAvailable(capability)
            if remote_code == "connection_required":
                if not remote_slot and isinstance(result, dict):
                    remote_slot = result.get("slot")
                raise ConnectionRequired(capability, remote_slot)
            if capability and (capability.startswith("payments.") or capability.startswith("email.")) \
                    and (status == 501 or isinstance(remote_code, str) and remote_code in UNAVAILABLE_CODES):
                raise PramaanNotAvailable(capability)
            uncertain = method == "POST" and status >= 500
            code = remote_code if isinstance(remote_code, str) and remote_code in {"forbidden", "approval_required"} else "request_rejected"
            raise PramaanError(code if not uncertain else "unavailable", uncertain=uncertain)
        if status not in {200, 201, 202} or not isinstance(result, dict):
            raise PramaanError("invalid_response", uncertain=method == "POST")
        return status, result

    def run(self, capability, inputs, *, idempotency_key=None, approved_by=None):
        self.require_configured()
        if capability not in self.CAPABILITIES:
            raise PramaanError("unsupported_capability")
        if capability in self.ACTIONS and not idempotency_key:
            raise PramaanError("missing_idempotency_key")
        if capability in {"llm.chat", "llm.complete"}:
            inputs = generation_request(inputs)
        status, result = self._request("POST", "/v1/capabilities/" + quote(capability, safe=""), inputs,
                                       idempotency_key=idempotency_key, approved_by=approved_by,
                                       capability=capability)
        if status == 202:
            if not isinstance(result.get("job_id"), str) or result.get("status") not in {"running", "done", "failed", "cancelled"}:
                raise PramaanError("invalid_response", uncertain=capability in self.ACTIONS)
        return generation_result(capability, inputs, result)

    def job(self, job_id):
        _, result = self._request("GET", "/v1/jobs/" + quote(job_id, safe=""))
        return result

    def call(self, capability, inputs, *, idempotency_key=None, approved_by=None, max_polls=60):
        result = self.run(capability, inputs, idempotency_key=idempotency_key, approved_by=approved_by)
        if "job_id" not in result:
            return result
        job_id = result["job_id"]
        for _ in range(max_polls):
            state = result.get("status")
            if state == "done":
                completed = result.get("result")
                if not isinstance(completed, dict):
                    raise PramaanError("invalid_response", uncertain=capability in self.ACTIONS)
                return generation_result(capability, inputs, completed)
            if state in {"failed", "cancelled"}:
                raise PramaanError("job_failed", uncertain=capability in self.ACTIONS)
            if state != "running":
                raise PramaanError("invalid_response")
            self._sleep(2)
            result = self.job(job_id)
        raise PramaanError("job_pending", uncertain=capability in self.ACTIONS)

    def estimate(self, capability, inputs):
        """Ask what a call needs before running it; nothing runs and nothing is charged."""
        self.require_configured()
        if capability not in self.CAPABILITIES:
            raise PramaanError("unsupported_capability")
        _, result = self._request("POST", "/v1/capabilities/" + quote(capability, safe="") + "/estimate",
                                  inputs, capability=capability)
        if not isinstance(result.get("can_run"), bool):
            raise PramaanError("invalid_response")
        if result["can_run"] is False and result.get("reason") == "connection_required":
            raise ConnectionRequired(capability, result.get("slot"))
        return result

    # Feature contracts delivered on the platform catalogue; each stays false
    # until its own integration and fake checks are in place.
    FEATURES: ClassVar[dict[str, bool]] = {
        "fee_payments": True,
        "email_delivery": True,
    }

    def availability(self) -> tuple[FeatureAvailability, ...]:
        return tuple(
            FeatureAvailability(feature, enabled, "" if enabled else str(CapabilityUnavailable(feature)))
            for feature, enabled in self.FEATURES.items()
        )

    def payment_account_ready(self):
        """True only when the connected payment account can take charges."""
        result = self.call("payments.account.status", {})
        if result.get("status") not in {"ready", "pending", "restricted"}:
            raise PramaanError("invalid_response")
        return result.get("status") == "ready" and result.get("chargesEnabled") is True
