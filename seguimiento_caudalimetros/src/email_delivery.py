"""Server-side Resend transport, configuration and audit; no Outlook dependency."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import formataddr
from typing import Any

import requests

from src.config import Settings, _as_bool, _secret
from src.supabase_repository import _client

ADDRESS = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@"
                     r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}\Z")
TEST_SENDER = "onboarding@resend.dev"


def valid_email(value: str) -> bool:
    value = str(value or "").strip()
    return len(value) <= 254 and bool(ADDRESS.fullmatch(value))


def parse_recipients(value: str) -> list[str]:
    addresses = []
    for item in re.split(r"[,;\s]+", str(value or "").strip()):
        if not item:
            continue
        if not valid_email(item):
            raise ValueError(f"Dirección de correo inválida: {item[:80]}")
        if item.casefold() not in {v.casefold() for v in addresses}:
            addresses.append(item)
    return addresses


@dataclass(frozen=True)
class EmailSettings:
    api_key: str = field(default="", repr=False)
    from_email: str = "caudales@OSgam"
    from_name: str = "OS GAM · Caudales"
    reply_to: str = ""
    dashboard_url: str = ""
    test_mode: bool = True
    test_recipient: str = ""

    @classmethod
    def load(cls):
        return cls(
            api_key=str(_secret("email", "resend_api_key", "RESEND_API_KEY", "")).strip(),
            from_email=str(_secret("email", "from_email", "EMAIL_FROM", "caudales@OSgam")).strip(),
            from_name=str(_secret("email", "from_name", "EMAIL_FROM_NAME", "OS GAM · Caudales")).strip(),
            reply_to=str(_secret("email", "reply_to", "EMAIL_REPLY_TO", "")).strip(),
            dashboard_url=str(_secret("email", "dashboard_url", "DASHBOARD_URL", "")).strip(),
            test_mode=_as_bool(_secret("email", "test_mode", "EMAIL_TEST_MODE", "true")),
            test_recipient=str(_secret("email", "test_recipient", "EMAIL_TEST_RECIPIENT", "")).strip(),
        )

    @property
    def sender_email(self) -> str:
        return TEST_SENDER if self.test_mode else self.from_email

    def errors(self) -> list[str]:
        errors = []
        if not self.api_key:
            errors.append("Falta configurar email.resend_api_key en los Secrets del aplicativo.")
        if not valid_email(self.sender_email):
            errors.append("El remitente necesita un dominio completo y verificable. caudales@OSgam está incompleto.")
        if not self.test_mode and self.sender_email.lower().endswith("@resend.dev"):
            errors.append("El dominio resend.dev solo se utiliza en modo de prueba.")
        if self.test_mode and not valid_email(self.test_recipient):
            errors.append("Para probar sin dominio, configure email.test_recipient con el correo de su cuenta Resend.")
        if self.reply_to and not valid_email(self.reply_to):
            errors.append("email.reply_to no contiene una dirección válida.")
        if any(c in self.from_name for c in '\r\n<>'):
            errors.append("El nombre del remitente contiene caracteres inválidos.")
        return errors


def build_payload(settings: EmailSettings, *, recipients: list[str], cc: list[str], subject: str,
                  html: str, text: str) -> dict[str, Any]:
    issues = settings.errors()
    if issues:
        raise ValueError(" ".join(issues))
    if not recipients or len(recipients) + len(cc) > 50:
        raise ValueError("Ingrese entre 1 y 50 destinatarios, contando las copias.")
    if not all(valid_email(address) for address in recipients + cc):
        raise ValueError("Hay direcciones de correo inválidas.")
    if not subject.strip() or len(subject) > 200 or '\n' in subject or '\r' in subject:
        raise ValueError("El asunto debe tener entre 1 y 200 caracteres, sin saltos de línea.")
    if settings.test_mode and (cc or len(recipients) != 1 or
                              recipients[0].casefold() != settings.test_recipient.casefold()):
        raise ValueError("En modo de prueba solo puede enviar al correo de su cuenta Resend, sin copias.")
    payload = {"from": formataddr((settings.from_name, settings.sender_email)), "to": recipients,
               "subject": subject.strip(), "html": html, "text": text}
    if cc:
        payload["cc"] = cc
    if settings.reply_to:
        payload["reply_to"] = settings.reply_to
    return payload


class DeliveryError(RuntimeError):
    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


class ResendDelivery:
    def __init__(self, settings: EmailSettings):
        self.settings = settings

    def send(self, payload: dict[str, Any], request_id: str) -> str:
        # Validate at the transport boundary too, even when called outside the UI.
        expected = build_payload(self.settings, recipients=payload.get("to", []), cc=payload.get("cc", []),
                                 subject=payload.get("subject", ""), html=payload.get("html", ""), text=payload.get("text", ""))
        if payload != expected:
            raise ValueError("El contenido del envío no coincide con la configuración autorizada.")
        try:
            response = requests.post("https://api.resend.com/emails", json=payload,
                                     headers={"Authorization": f"Bearer {self.settings.api_key}",
                                              "Idempotency-Key": f"caudalimetros-{request_id}"},
                                     timeout=(10, 45), allow_redirects=False)
        except requests.RequestException:
            raise DeliveryError("No se pudo confirmar el envío. Revise Resend o reintente esta misma solicitud; "
                                "se conserva su identificador para evitar duplicados.", uncertain=True) from None
        if not 200 <= response.status_code < 300:
            messages = {401: "Resend rechazó la clave API. Revise los Secrets.",
                        403: "Resend no autoriza el remitente o el destinatario. Verifique el dominio o el correo de prueba.",
                        409: "Resend detectó un conflicto con la solicitud. Consulte el historial antes de generar otra.",
                        422: "Resend rechazó los datos del correo. Revise remitente, destinatarios y configuración.",
                        429: "Se alcanzó un límite de Resend. Espere o revise la cuota disponible."}
            raise DeliveryError(messages.get(response.status_code, f"Resend no confirmó el envío (HTTP {response.status_code})."),
                                uncertain=response.status_code >= 500 or response.status_code in {408, 409})
        try:
            message_id = response.json().get("id")
        except (ValueError, AttributeError):
            message_id = None
        if not isinstance(message_id, str) or not message_id:
            raise DeliveryError("Resend respondió sin identificador. Compruebe el envío en Resend antes de repetirlo.", uncertain=True)
        return message_id


class EmailAuditRepository:
    def __init__(self, settings: Settings):
        self.client = _client(settings)
        self.table = "caudalimetro_reportes_envios"

    def prepare(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self.client.table(self.table).select("*").eq("id", payload["id"]).execute().data or []
        if rows:
            return rows[0]
        rows = self.client.table(self.table).insert(payload).execute().data or []
        if not rows:
            raise RuntimeError("No fue posible registrar la solicitud de correo.")
        return rows[0]

    def update(self, request_id: str, **values: Any) -> None:
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        rows = self.client.table(self.table).update(values).eq("id", request_id).execute().data or []
        if not rows:
            raise RuntimeError("No fue posible actualizar el estado del correo.")

    def history(self) -> list[dict[str, Any]]:
        result = self.client.table(self.table).select(
            "created_at,status,subject,sender,recipients,cc,total_rows,provider_message_id,error"
        ).order("created_at", desc=True).limit(50).execute()
        return result.data or []
