from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from src.dashboard import (
    GRAY, GREEN, RED, build_dashboard_tables, export_csv, filter_dashboard,
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
