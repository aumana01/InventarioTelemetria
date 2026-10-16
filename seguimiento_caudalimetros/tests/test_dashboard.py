from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from src.dashboard import (
    GRAY, GREEN, RED, TELEMETRY_ASPECTS, build_dashboard_tables,
    export_csv, filter_dashboard, filter_telemetry_pending,
    period_bounds, review_date, style_status_row,
)
from src.supabase_repository import SupabaseReviewRepository

TODAY = date(2026, 10, 5)
INVENTORY = [
    {"ID equipo": "A", "Sistema": "Guadalupe", "Equipo": "Salida", "Tipo": "Ultrasónico"},
    {"ID equipo": "B", "Sistema": "La Valencia", "Equipo": "Entrada", "Tipo": "Inserción"},
]


def review(**changes):
    result = {
        "id": "new", "equipment_key": "A", "reviewed_at": "2026-10-05T18:00:00+00:00",
        "equipment_type": "Ultrasónico", "measurement_quality": "Buena",
        "rectification_status": "Sí, con medición simultánea",
        "maintenance_gel_date": "2026-10-01",
        "maintenance_transducers_alignment_date": "2026-10-01",
        "maintenance_internal_download_date": "2026-10-01",
        "maintenance_simultaneous_installation_date": "2026-10-01",
        "maintenance_scada_check_date": "2026-10-01", "maintenance_scada_working": True,
    }
    result.update(changes)
    return result


@pytest.mark.parametrize("period,start", [
    ("Última semana", date(2026, 9, 29)), ("Último mes", date(2026, 9, 5)),
    ("Últimos 2 meses", date(2026, 8, 5)), ("Último trimestre", date(2026, 7, 5)),
    ("Último año", date(2025, 10, 5)),
])
def test_periods_are_rolling_and_inclusive(period, start):
    assert period_bounds(period, TODAY) == (start, TODAY)


def test_specific_custom_and_month_end_dates():
    assert period_bounds("Fecha específica", TODAY, specific=TODAY) == (TODAY, TODAY)
    assert period_bounds("Último mes", date(2026, 3, 31))[0] == date(2026, 2, 28)
    with pytest.raises(ValueError):
        period_bounds("Rango personalizado", TODAY, custom=(TODAY, date(2026, 9, 1)))
    assert review_date("2026-10-05T03:00:00Z") == date(2026, 10, 4)


def test_latest_is_selected_before_filtering_and_unreviewed_stays_visible():
    old = review(id="old", reviewed_at="2026-09-01T18:00:00Z", repair_signal_pending=True)
    summary, _ = build_dashboard_tables(INVENTORY, [old, review()], today=TODAY)
    assert len(summary) == 2
    assert summary.iloc[0]["Semáforo"] == GREEN
    assert summary.iloc[1]["Estado"] == "Sin revisión"
    assert summary.iloc[1]["Semáforo"] == RED
    assert filter_dashboard(summary, start=date(2026, 9, 1), end=date(2026, 9, 30)).empty
    summary_history, _ = build_dashboard_tables(INVENTORY, [old, review()], history=True, today=TODAY)
    found = filter_dashboard(summary_history, start=date(2026, 9, 1), end=date(2026, 9, 30))
    assert found["Registro"].tolist() == ["old"]


def test_latest_orders_absolute_timestamps_not_timezone_strings():
    summary, _ = build_dashboard_tables(INVENTORY, [
        review(id="older", reviewed_at="2026-10-05T18:00:00+02:00"),
        review(id="latest", reviewed_at="2026-10-05T17:00:00Z"),
    ], today=TODAY)
    assert summary.iloc[0]["Registro"] == "latest"


def test_maintenance_repairs_and_general_states():
    summary, detail = build_dashboard_tables(INVENTORY, [review(
        maintenance_gel_date="2026-01-01", repair_software_firmware_pending=True,
        maintenance_internal_download_applicable=False, maintenance_scada_working=False,
        measurement_quality="Mala",
    )], today=TODAY)
    detail = detail[detail["ID equipo"] == "A"].set_index("Aspecto")
    assert detail.loc["Cambio de gel", "Semáforo"] == RED
    assert detail.loc["Cambio de gel", "Vence"] == date(2026, 7, 1)
    assert detail.loc["Descarga de datos internos", "Semáforo"] == GRAY
    assert detail.loc["Funcionamiento en SCADA", "Semáforo"] == RED
    assert detail.loc["Actualización de Software / Firmware", "Estado"] == "Pendiente"
    assert detail.loc["Calidad de medición", "Semáforo"] == RED
    assert summary.iloc[0]["Pendientes rojos"] == 4


def test_sin_medicion_no_reporta_calidad_roja():
    summary, detail = build_dashboard_tables(INVENTORY, [review(
        rectification_status="No se ha realizado",
        measurement_quality=None,
        review_date="2026-10-03",
    )], today=TODAY)
    assert summary.iloc[0]["Fecha de revisión"] == date(2026, 10, 3)
    assert summary.iloc[0]["Calidad"] == "No aplica"
    point = detail[(detail["ID equipo"] == "A") & (detail["Aspecto"] == "Calidad de medición")].iloc[0]
    assert point["Semáforo"] == GRAY
    assert point["Estado"] == "No aplica (sin medición simultánea)"
    assert detail[(detail["ID equipo"] == "A") & (detail["Aspecto"] == "Rectificación")].iloc[0]["Semáforo"] == RED


def test_puntual_has_flow_and_no_rectification_alert():
    summary, details = build_dashboard_tables(INVENTORY, [review(
        measurement_method="puntual",
        point_flow_lps=42.5,
        measurement_quality=None,
        rectification_status="No se ha realizado",
    )], today=TODAY)
    row = summary[summary["ID equipo"] == "A"].iloc[0]
    assert row["Caudal puntual (L/s)"] == 42.5
    assert row["Modalidad de medición"] == "Puntual"
    statuses = details[details["ID equipo"] == "A"].set_index("Aspecto")
    assert statuses.loc["Calidad de medición", "Semáforo"] == GRAY
    assert statuses.loc["Rectificación", "Semáforo"] == GRAY


def test_telemetry_filter_includes_exact_five_pending_aspects():
    assert set(TELEMETRY_ASPECTS) == {
        "Señal", "Visualización en Perspective", "Vision Client CCO",
        "Vision Client SCADA vr2", "Descarga módulo de reportes",
    }

    changes = {
        "repair_signal_pending": True,
        "repair_perspective_pending": True,
        "repair_vision_cco_pending": True,
        "repair_vision_scada_vr2_pending": True,
        "repair_vision_reports_pending": True,
        "repair_power_pending": True,
        "repair_calibration_pending": True,
    }
    summary, detail = build_dashboard_tables(INVENTORY, [review(**changes)], today=TODAY)
    selected_summary = filter_telemetry_pending(summary, detail)
    assert selected_summary["ID equipo"].tolist() == ["A"]
    assert selected_summary.iloc[0]["Pendientes Telemetría"] == 5
    assert set(selected_summary.iloc[0]["Detalle pendientes Telemetría"].split("; ")) == set(TELEMETRY_ASPECTS)

    selected_detail = filter_telemetry_pending(detail, detail)
    assert len(selected_detail) == 5
    assert set(selected_detail["Aspecto"]) == set(TELEMETRY_ASPECTS)
    assert set(selected_detail["Semáforo"]) == {RED}
    assert "Energía" not in set(selected_detail["Aspecto"])
    assert "Calibración" not in set(selected_detail["Aspecto"])


def test_telemetry_filter_excludes_other_red_flags_and_resolved_signals():
    summary, detail = build_dashboard_tables(INVENTORY, [
        review(
            repair_signal_pending=False,
            repair_power_pending=True,
            repair_calibration_pending=True,
            maintenance_gel_date="2026-01-01",
        )
    ], today=TODAY)
    assert summary.iloc[0]["Pendientes Telemetría"] == 0
    assert summary.iloc[0]["Semáforo"] == RED
    assert filter_telemetry_pending(summary, detail).empty
    assert filter_telemetry_pending(detail, detail).empty


def test_telemetry_filter_respects_selected_aspects_and_current_vs_history():
    latest = review(
        id="new", reviewed_at="2026-10-05T18:00:00Z",
        repair_signal_pending=False,
        repair_vision_cco_pending=True,
    )
    old = review(
        id="old", reviewed_at="2026-09-01T18:00:00Z",
        repair_signal_pending=True,
        repair_vision_cco_pending=False,
    )
    summary, detail = build_dashboard_tables(INVENTORY, [old, latest], today=TODAY)
    assert filter_telemetry_pending(summary, detail, ["Señal"]).empty
    selected = filter_telemetry_pending(summary, detail, ["Vision Client CCO"])
    assert selected["Registro"].tolist() == ["new"]
    assert selected.iloc[0]["Pendientes Telemetría"] == 1
    assert selected.iloc[0]["Detalle pendientes Telemetría"] == "Vision Client CCO"

    h_summary, h_detail = build_dashboard_tables(INVENTORY, [old, latest],
                                                 history=True, today=TODAY)
    history_signal = filter_telemetry_pending(h_summary, h_detail, ["Señal"])
    assert history_signal["Registro"].tolist() == ["old"]
    history_cco = filter_telemetry_pending(h_detail, h_detail, ["Vision Client CCO"])
    assert history_cco["Registro"].tolist() == ["new"]
    assert filter_telemetry_pending(h_summary, h_detail, []).empty

    by_system = filter_dashboard(h_summary, selections={"Sistema": ["Guadalupe"]},
                                 start=date(2026, 9, 1), end=date(2026, 9, 30))
    assert filter_telemetry_pending(by_system, h_detail, ["Señal"])["Registro"].tolist() == ["old"]


def test_filters_combine_exact_date_system_state_type_and_search():
    _, detail = build_dashboard_tables(INVENTORY, [review(repair_signal_pending=True)], today=TODAY)
    result = filter_dashboard(detail, selections={"Sistema": ["Guadalupe"], "Semáforo": [RED],
        "Tipo de equipo": ["Ultrasónico"], "Aspecto": ["Señal"]}, start=TODAY, end=TODAY,
        query="guadalupe señal")
    assert result["Aspecto"].tolist() == ["Señal"]
    assert filter_dashboard(detail, start=TODAY, end=TODAY, only_unreviewed=True).empty
    undated = filter_dashboard(detail, start=TODAY, end=TODAY, only_unreviewed=True, include_undated=True)
    assert undated["ID equipo"].tolist() == ["B"]
    assert filter_dashboard(detail, query="nada coincide").empty
    assert filter_dashboard(detail.iloc[:0], query="buscar").empty


def test_empty_or_removed_inventory_history_and_csv():
    summary, detail = build_dashboard_tables([], [], today=TODAY)
    assert summary.empty and detail.empty and "Semáforo" in summary.columns
    summary, _ = build_dashboard_tables([], [review(geodatabase_snapshot={"OBSERVACIO": "Tres Ríos",
                                                                            "DESCRIPCIO": "Captación"})], today=TODAY)
    assert summary.iloc[0]["Sistema"] == "Tres Ríos"
    assert summary.iloc[0]["Equipo"] == "Captación"
    payload = export_csv(pd.DataFrame({"Registro": ["secret"], "Equipo": ["=SUM(1,2)"]})).decode("utf-8-sig")
    assert "Registro" not in payload and "'=SUM" in payload
    assert "#fde8e7" in style_status_row(pd.Series({"Semáforo": RED}))[0]
    assert "#e3f4e9" in style_status_row(pd.Series({"Semáforo": GREEN}))[0]


def test_repository_reads_beyond_500_and_server_page_caps():
    rows = [{"id": str(i)} for i in range(1203)]
    ranges = []
    class Query:
        def select(self, *_args): return self
        def order(self, *_args, **_kwargs): return self
        def range(self, start, end):
            self.start, self.end = start, min(end, start + 199)
            ranges.append((start, end))
            return self
        def execute(self): return SimpleNamespace(data=rows[self.start:self.end + 1])
    repo = object.__new__(SupabaseReviewRepository)
    repo.table_name = "revisiones"
    repo.client = SimpleNamespace(table=lambda name: Query())
    assert repo.list_dashboard_reviews() == rows
    assert ranges[-1][0] == 1203
    with pytest.raises(ValueError): repo.list_dashboard_reviews(page_size=0)
