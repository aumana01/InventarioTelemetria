from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.dashboard import LOCAL_ZONE, RED
from src.email_delivery import (
    DeliveryError, EmailAuditRepository, EmailSettings, ResendDelivery, build_payload, parse_recipients,
)
from src.email_report import build_email_report


def render_email_module(frame: pd.DataFrame, *, context: Mapping[str, Any],
                        settings: EmailSettings, audit: EmailAuditRepository | None = None,
                        demo_mode: bool = False) -> None:
    st.markdown("---")
    st.subheader("Reporte por correo")
    st.caption("Prepare un reporte con los resultados filtrados, sin adjuntos. La vista previa funciona aunque Resend todavía no esté configurado.")
    with st.expander("Preparar reporte y ver correo", expanded=False):
        c1, c2 = st.columns(2)
        title = c1.text_input("Título del reporte", value="Seguimiento de caudalímetros", max_chars=120, key="email-title")
        author = c2.text_input("Preparado por", max_chars=120, key="email-author")
        intro = st.text_area("Mensaje introductorio", value="Se remite el seguimiento de caudalímetros para conocimiento y atención de los pendientes identificados.",
                             max_chars=1600, height=90, key="email-intro")
        r1, r2 = st.columns(2)
        pending_only = r1.checkbox("Enviar únicamente estados rojos", key="email-pending-only")
        max_rows = r2.selectbox("Máximo de filas en el correo", [25, 50, 100, 200], index=1, key="email-max-rows")
        chosen = frame.loc[frame["Semáforo"] == RED].copy() if pending_only else frame.copy()
        if chosen.empty:
            st.info("No hay estados rojos en los resultados filtrados. Desmarque la opción para preparar el reporte completo.")
            return
        filters = dict(context.get("filters", {}))
        filters["Contenido del correo"] = "Solo estados rojos" if pending_only else "Todos los resultados filtrados"
        effective_context = {"scope": context.get("scope", "Estado actual"), "filters": filters}
        source = json.dumps({"data": chosen.to_json(date_format="iso"), "context": effective_context,
                             "title": title, "author": author, "intro": intro, "max_rows": max_rows,
                             "url": settings.dashboard_url}, sort_keys=True, ensure_ascii=False)
        source_digest = hashlib.sha256(source.encode()).hexdigest()
        if st.session_state.get("email-report-source") != source_digest:
            st.session_state["email-report-source"] = source_digest
            st.session_state["email-report-clock"] = datetime.now(LOCAL_ZONE)
        try:
            report = build_email_report(chosen, title=title or "Seguimiento de caudalímetros", author=author,
                                        intro=intro, max_rows=max_rows, dashboard_url=settings.dashboard_url,
                                        generated_at=st.session_state["email-report-clock"], **effective_context)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.caption(f"Reporte: {report.equipment_count} equipo(s), {report.total_rows} registro(s). "
                   f"Detalle incluido: {report.shown_rows} fila(s), priorizando los rojos.")
        st.markdown("**Vista previa del mensaje**")
        components.html(report.html, height=720, scrolling=True)
        st.download_button("Descargar vista previa HTML", report.html.encode("utf-8"),
                           file_name="reporte_caudalimetros.html", mime="text/html", key="email-preview-download")
        st.markdown("#### Destinatarios y envío")
        if settings.test_mode:
            st.info("Modo de prueba: el correo saldrá desde onboarding@resend.dev y solo se puede enviar al correo con el que creó su cuenta Resend.")
            st.caption(f"Remitente previsto para producción: {settings.from_email}. Debe utilizar un dominio completo y verificado.")
        st.write(f"**Remitente del envío:** {settings.from_name} <{settings.sender_email}>")
        if settings.reply_to:
            st.caption(f"Las respuestas se dirigirán a: {settings.reply_to}")
        to_text = st.text_area("Destinatarios", value=settings.test_recipient if settings.test_mode else "",
                               placeholder="correo@dominio.com; otro@dominio.com", height=70, key="email-to")
        cc_text = st.text_input("Con copia (opcional)", disabled=settings.test_mode, key="email-cc")
        subject = st.text_input("Asunto", value="Reporte de seguimiento de caudalímetros · OS GAM", max_chars=200, key="email-subject")
        errors = settings.errors()
        if demo_mode:
            errors.append("En modo demostración puede revisar el diseño; los envíos están deshabilitados.")
        if audit is None:
            errors.append("Conecte Supabase para registrar las solicitudes de correo.")
        payload = None
        recipients, cc = [], []
        try:
            recipients = parse_recipients(to_text)
            cc = [v for v in parse_recipients(cc_text if not settings.test_mode else "")
                  if v.casefold() not in {r.casefold() for r in recipients}]
            if not recipients:
                errors.append("Ingrese al menos un destinatario.")
            if not settings.errors() and recipients:
                payload = build_payload(settings, recipients=recipients, cc=cc, subject=subject,
                                        html=report.html, text=report.text)
        except ValueError as exc:
            errors.append(str(exc))
        for error in dict.fromkeys(errors):
            st.caption(error)
        with st.expander("Configuración de correo"):
            st.markdown("Configure la sección **[email]** en Settings → Secrets de Streamlit. La clave API permanece en el servidor.")
            st.code('''[email]
resend_api_key = "CLAVE_API_RESEND"
from_email = "caudales@OSgam"
from_name = "OS GAM · Caudales"
test_mode = true
test_recipient = "CORREO_DE_TU_CUENTA_RESEND"
reply_to = ""
dashboard_url = "URL_PUBLICA_DEL_APLICATIVO"''', language="toml")
            st.caption("Para producción: reemplace from_email por una dirección con dominio completo verificado en Resend y cambie test_mode a false. "
                       "Ejecute migration_20261005_email_reports.sql para el historial de correos.")
        fingerprint = hashlib.sha256(json.dumps(payload or {"source": source_digest, "to": to_text, "subject": subject},
                                                sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        state = st.session_state.get("email-send-state")
        if not state or state["fingerprint"] != fingerprint:
            state = {"fingerprint": fingerprint, "request_id": str(uuid.uuid4()), "status": "prepared",
                     "created_at": datetime.now(timezone.utc).isoformat()}
            st.session_state["email-send-state"] = state
        expired = datetime.now(timezone.utc) - datetime.fromisoformat(state["created_at"]) >= timedelta(hours=23)
        if state["status"] == "accepted":
            st.success(f"Resend aceptó el correo. ID: {state.get('message_id', '')}. Esto no confirma su entrega en la bandeja del destinatario.")
            if state.get("audit_warning"):
                st.warning("El proveedor aceptó el correo, pero no se pudo actualizar el historial. Consulte Resend antes de repetirlo.")
        elif state.get("error"):
            st.warning(state["error"])
        if expired and state["status"] != "accepted":
            st.warning("La solicitud es antigua. Revise su estado en Resend antes de preparar un nuevo envío.")
        if st.button("Enviar reporte por correo", type="primary", key="email-send",
                     disabled=bool(errors) or payload is None or state["status"] == "accepted" or expired):
            audit_payload = {"id": state["request_id"], "status": "prepared", "subject": payload["subject"],
                             "sender": settings.sender_email, "recipients": recipients, "cc": cc,
                             "scope": effective_context["scope"], "filters": filters,
                             "total_rows": report.total_rows, "shown_rows": report.shown_rows,
                             "equipment_count": report.equipment_count,
                             "html_sha256": hashlib.sha256(report.html.encode()).hexdigest(),
                             "test_mode": settings.test_mode}
            try:
                existing = audit.prepare(audit_payload)
            except Exception:
                st.error("No se pudo registrar la solicitud. Revise la conexión a Supabase y ejecute migration_20261005_email_reports.sql. No se envió el correo.")
                return
            if existing.get("status") == "accepted":
                state.update(status="accepted", message_id=existing.get("provider_message_id", ""))
                st.rerun()
            with st.spinner("Enviando el reporte..."):
                try:
                    message_id = ResendDelivery(settings).send(payload, state["request_id"])
                except (DeliveryError, ValueError) as exc:
                    state.update(status="unknown" if getattr(exc, "uncertain", False) else "error", error=str(exc))
                    try:
                        audit.update(state["request_id"], status=state["status"], error=str(exc))
                    except Exception:
                        pass
                    st.rerun()
                state.update(status="accepted", message_id=message_id, error="")
                try:
                    audit.update(state["request_id"], status="accepted", provider_message_id=message_id, error=None)
                except Exception:
                    state["audit_warning"] = True
                st.rerun()
        if state["status"] == "accepted" or expired:
            def reset_send():
                st.session_state.pop("email-send-state", None)
            st.button("Preparar otro envío", key="email-new-send", on_click=reset_send)

    if audit is not None and st.button("Consultar historial de correos", key="email-history"):
        try:
            history = pd.DataFrame(audit.history())
            if history.empty:
                st.info("Todavía no hay solicitudes de correo registradas.")
            else:
                history["status"] = history["status"].map({"prepared": "Preparado", "accepted": "Aceptado por Resend",
                                                           "error": "Error", "unknown": "Sin confirmación"}).fillna(history["status"])
                st.dataframe(history.rename(columns={"created_at": "Fecha", "status": "Estado", "subject": "Asunto",
                                                     "sender": "Remitente", "recipients": "Destinatarios", "cc": "Copias",
                                                     "total_rows": "Registros", "provider_message_id": "ID Resend", "error": "Detalle"}),
                             hide_index=True, width="stretch")
        except Exception:
            st.info("No se pudo consultar el historial. Revise Supabase y la migración migration_20261005_email_reports.sql.")
