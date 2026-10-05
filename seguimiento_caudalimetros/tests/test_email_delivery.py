from dataclasses import replace

import pytest
import requests

from src.email_delivery import (
    DeliveryError, EmailSettings, ResendDelivery, build_payload, parse_recipients, valid_email,
)


def settings():
    return EmailSettings(api_key="secret-not-for-output", test_mode=True, test_recipient="owner@example.org")


def payload(config=None):
    return build_payload(config or settings(), recipients=["owner@example.org"], cc=[], subject="Reporte OS GAM",
                         html="<p>reporte</p>", text="reporte")


def test_email_config_requires_complete_domain_and_keeps_key_private():
    assert not valid_email("caudales@OSgam")
    assert valid_email("caudales@osgam.example")
    assert not valid_email("x@domain.com\nBcc: y@domain.com")
    config = replace(settings(), test_mode=False)
    assert config.errors()
    assert "secret-not-for-output" not in repr(config)
    assert not settings().errors()
    assert payload()["from"].endswith("<onboarding@resend.dev>")
    production = replace(config, from_email="caudales@osgam.example", reply_to="reply@example.org")
    result = payload(production)
    assert result["reply_to"] == "reply@example.org"
    assert "attachments" not in result


def test_recipient_validation_deduplication_and_test_only_owner():
    assert parse_recipients("a@example.org; A@example.org\nb@example.org") == ["a@example.org", "b@example.org"]
    with pytest.raises(ValueError): parse_recipients("valid@example.org, invalid")
    with pytest.raises(ValueError):
        build_payload(settings(), recipients=["other@example.org"], cc=[], subject="x", html="x", text="x")
    with pytest.raises(ValueError):
        build_payload(settings(), recipients=["owner@example.org"], cc=["copy@example.org"], subject="x", html="x", text="x")
    with pytest.raises(ValueError):
        build_payload(settings(), recipients=["owner@example.org"], cc=[], subject="x\nBcc: x", html="x", text="x")


def test_request_uses_inline_body_idempotency_and_no_attachments(monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        class Response:
            status_code = 200
            def json(self): return {"id": "resend-id"}
        return Response()
    monkeypatch.setattr(requests, "post", post)
    sender = ResendDelivery(settings())
    assert sender.send(payload(), "same-request") == "resend-id"
    assert sender.send(payload(), "same-request") == "resend-id"
    assert calls[0][0] == "https://api.resend.com/emails"
    assert calls[0][1]["headers"]["Idempotency-Key"] == calls[1][1]["headers"]["Idempotency-Key"]
    assert not calls[0][1]["allow_redirects"]
    assert "attachments" not in calls[0][1]["json"]
    assert calls[0][1]["json"]["html"] == "<p>reporte</p>"
    altered = payload()
    altered["from"] = "other@example.org"
    with pytest.raises(ValueError): sender.send(altered, "x")
    assert len(calls) == 2


@pytest.mark.parametrize("status,uncertain", [(401, False), (403, False), (422, False), (429, False), (500, True)])
def test_http_errors_are_sanitized_and_uncertain_delivery_is_explicit(monkeypatch, status, uncertain):
    class Response:
        status_code = status
        def json(self): return {"message": "secret-not-for-output"}
    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: Response())
    with pytest.raises(DeliveryError) as error:
        ResendDelivery(settings()).send(payload(), "same-request")
    assert error.value.uncertain is uncertain
    assert "secret-not-for-output" not in str(error.value)


def test_timeout_never_claims_delivery(monkeypatch):
    def post(*_args, **_kwargs): raise requests.Timeout("sensitive request")
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(DeliveryError) as error:
        ResendDelivery(settings()).send(payload(), "same-request")
    assert error.value.uncertain
    assert "sensitive request" not in str(error.value)
