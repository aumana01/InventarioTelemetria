import pytest
from streamlit.testing.v1 import AppTest
from src.email_delivery import DeliveryError, ResendDelivery

SCRIPT = '''
import pandas as pd
import streamlit as st
from src.dashboard import RED
from src.email_delivery import EmailSettings
from src.email_ui import render_email_module
class Audit:
    def prepare(self, payload):
        if st.session_state.get("reject_audit"):
            raise RuntimeError("missing table")
        st.session_state["audit_record"] = payload
        return payload
    def update(self, request_id, **values):
        st.session_state["audit_record"].update(values)
    def history(self): return []
frame = pd.DataFrame([{"ID equipo": "FM-01", "Sistema": "Guadalupe", "Equipo": "Salida",
    "Tipo de equipo": "Ultrasónico", "Semáforo": RED, "Estado": "Con pendientes",
    "Fecha de revisión": None, "Detalle de pendientes": "Calibración: Pendiente"}])
config = EmailSettings(api_key="fake", test_recipient="owner@example.org")
render_email_module(frame, context={"scope": "Estado actual", "filters": {"Sistema": ["Guadalupe"]}},
                    settings=config, audit=Audit())
'''


def test_preview_works_before_configuration_and_invalid_domain_blocks_send(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    at = AppTest.from_string(SCRIPT.replace('api_key="fake"', 'api_key=""'), default_timeout=30).run()
    assert not at.exception
    assert at.button(key="email-send").disabled
    assert at.get("iframe")
    at = AppTest.from_string(SCRIPT.replace('api_key="fake"', 'api_key="fake", test_mode=False'), default_timeout=30).run()
    assert not at.exception
    assert at.button(key="email-send").disabled
    assert any("dominio completo" in c.value for c in at.caption)


def test_accepted_email_cannot_be_sent_twice_on_rerun(monkeypatch):
    calls = []
    def send(self, payload, request_id):
        calls.append((payload, request_id))
        return "accepted-id"
    monkeypatch.setattr(ResendDelivery, "send", send)
    at = AppTest.from_string(SCRIPT, default_timeout=30).run()
    assert not at.exception and not at.button(key="email-send").disabled
    at.button(key="email-send").click().run()
    assert not at.exception
    assert len(calls) == 1
    assert at.button(key="email-send").disabled
    assert at.session_state["audit_record"]["status"] == "accepted"
    assert any("no confirma" in m.value for m in at.success)
    at.run()
    assert len(calls) == 1
    at.button(key="email-new-send").click().run()
    assert not at.button(key="email-send").disabled
    at.button(key="email-send").click().run()
    assert len(calls) == 2 and calls[0][1] != calls[1][1]


def test_uncertain_retry_preserves_exact_payload_and_id(monkeypatch):
    calls = []
    def send(self, payload, request_id):
        calls.append((payload, request_id))
        if len(calls) == 1:
            raise DeliveryError("Sin confirmación", uncertain=True)
        return "accepted-id"
    monkeypatch.setattr(ResendDelivery, "send", send)
    at = AppTest.from_string(SCRIPT, default_timeout=30).run()
    at.button(key="email-send").click().run()
    assert not at.exception
    assert at.session_state["audit_record"]["status"] == "unknown"
    at.button(key="email-send").click().run()
    assert not at.exception
    assert calls[0] == calls[1]
    assert at.button(key="email-send").disabled


def test_missing_audit_migration_does_not_send_any_email(monkeypatch):
    def send(*_args, **_kwargs): pytest.fail("No email should be sent")
    monkeypatch.setattr(ResendDelivery, "send", send)
    at = AppTest.from_string(SCRIPT, default_timeout=30).run()
    at.session_state["reject_audit"] = True
    at.button(key="email-send").click().run()
    assert not at.exception
    assert any("No se envió" in e.value for e in at.error)
