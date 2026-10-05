from datetime import datetime, timezone

import pandas as pd
import pytest

from src.dashboard import GREEN, RED
from src.email_report import MAX_HTML_BYTES, build_email_report, safe_dashboard_url


def sample():
    return pd.DataFrame([
        {"ID equipo": "FM-01", "Sistema": "Guadalupe", "Equipo": "Entrada verde", "Tipo de equipo": "Ultrasónico",
         "Semáforo": GREEN, "Estado": "Sin pendientes", "Fecha de revisión": None, "Detalle de pendientes": ""},
        {"ID equipo": "FM-02", "Sistema": "La Valencia", "Equipo": "Salida roja", "Tipo de equipo": "Inserción",
         "Semáforo": RED, "Estado": "Con pendientes", "Fecha de revisión": None,
         "Detalle de pendientes": "Calibración: Pendiente"},
    ])


def test_report_keeps_colors_totals_filters_and_prioritizes_red():
    frame = sample()
    original = frame.copy(deep=True)
    report = build_email_report(frame, filters={"Sistema": ["Guadalupe", "La Valencia"], "Período": "Último mes"},
                                dashboard_url="https://visor.example.org/", max_rows=1,
                                generated_at=datetime(2026, 10, 5, 21, 0, tzinfo=timezone.utc))
    assert report.total_rows == 2 and report.shown_rows == 1 and report.equipment_count == 2
    assert "Salida roja" in report.html and "Entrada verde" not in report.html
    assert "#fff1ef" in report.html and "Último mes" in report.html
    assert "Se muestran 1 de 2" in report.html
    assert "05/10/2026 · 15:00" in report.html
    assert 'href="https://visor.example.org/"' in report.html
    pd.testing.assert_frame_equal(frame, original)
    full = build_email_report(frame)
    assert "#edf8f1" in full.html and "Entrada verde" in full.text


def test_escapes_all_user_and_inventory_content_and_rejects_script_urls():
    frame = sample()
    frame.loc[0, "Equipo"] = '<script>alert("x")</script>'
    report = build_email_report(frame, title="<img src=x>", intro='<a href="evil">texto</a>',
                                author="<b>Autor</b>", filters={"Sistema": "<svg onload=x>"},
                                dashboard_url="javascript:alert(1)")
    assert "<script>" not in report.html and "<svg" not in report.html and "<img src=x>" not in report.html
    assert "&lt;script&gt;" in report.html and "&lt;a href=" in report.html
    assert "Consultar Dashboard</a>" not in report.html
    assert safe_dashboard_url("https://user:password@example.org") == ""
    assert safe_dashboard_url("https://example.org\nInjected") == ""


def test_detail_dates_and_history_remain_distinct():
    frame = sample().iloc[[1]].copy()
    frame["Aspecto"] = "Actualización de Software / Firmware"
    frame["Categoría"] = "Reparación"
    frame["Fecha del aspecto"] = pd.Timestamp("2026-10-01").date()
    frame["Vence"] = pd.Timestamp("2026-11-01").date()
    report = build_email_report(frame, scope="Historial de revisiones · Detalle por aspecto")
    assert "Historial de revisiones" in report.html
    assert "Firmware" in report.html and "01/11/2026" in report.html
    assert "1 aspectos" in report.text


def test_report_body_has_size_limit_and_announces_omitted_rows():
    row = sample().iloc[1].to_dict()
    row["Detalle de pendientes"] = "Pendiente " + "á" * 1200
    frame = pd.DataFrame([{**row, "ID equipo": str(i)} for i in range(250)])
    report = build_email_report(frame, max_rows=200)
    assert len(report.html.encode()) <= MAX_HTML_BYTES
    assert report.shown_rows < report.total_rows
    assert f"Se muestran {report.shown_rows} de 250" in report.text
    assert report.equipment_count == 250
    with pytest.raises(ValueError): build_email_report(frame.iloc[:0])
