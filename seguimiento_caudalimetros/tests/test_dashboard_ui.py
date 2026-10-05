from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.dashboard import GREEN, RED

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_dashboard_navigation_is_independent_of_single_meter_selection(monkeypatch):
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    at.sidebar.radio[0].set_value("Dashboard").run()
    assert not at.exception
    assert at.title[0].value == "Dashboard"
    assert at.dataframe[0].value.shape[0] == 3
    assert not at.sidebar.selectbox
    at.selectbox(key="dashboard-table").set_value("Detalle por aspecto").run()
    assert not at.exception
    assert "Aspecto" in at.dataframe[0].value.columns
    at.selectbox(key="dashboard-period").set_value("Fecha específica").run()
    assert not at.exception
    assert len(at.dataframe) == 0
    at.checkbox(key="dashboard-undated").check().run()
    assert not at.exception
    assert at.dataframe[0].value.shape[0] == 3
    at.selectbox(key="dashboard-scope").set_value("Historial · todas las revisiones").run()
    assert not at.exception
    assert len(at.dataframe) == 0
    at.button(key="dashboard-reset").click().run()
    assert not at.exception


def test_filters_and_colored_tables_render_with_review_data():
    at = AppTest.from_string('''
from datetime import date
from src.dashboard_ui import render_dashboard
from src.dashboard import local_today
stamp = local_today().isoformat()
meters = [{"ID equipo": "A", "Sistema": "Guadalupe", "Equipo": "Salida"},
          {"ID equipo": "B", "Sistema": "La Valencia", "Equipo": "Entrada"}]
review = {
    "id": "1", "equipment_key": "A", "reviewed_at": stamp + "T18:00:00Z",
    "equipment_type": "Ultrasónico", "measurement_quality": "Buena",
    "rectification_status": "Sí, con medición simultánea", "maintenance_gel_date": stamp,
    "maintenance_transducers_alignment_date": stamp, "maintenance_internal_download_date": stamp,
    "maintenance_simultaneous_installation_date": stamp, "maintenance_scada_check_date": stamp,
    "maintenance_scada_working": True,
}
render_dashboard(meters, [review])
''', default_timeout=30).run()
    assert not at.exception
    assert at.dataframe[0].value["Semáforo"].tolist() == [GREEN, RED]
    at.multiselect(key="dashboard-filter-Semáforo").set_value([GREEN]).run()
    assert not at.exception
    assert at.dataframe[0].value["ID equipo"].tolist() == ["A"]
    at.selectbox(key="dashboard-table").set_value("Detalle por aspecto").run()
    at.multiselect(key="dashboard-filter-Aspecto").set_value(["Señal"]).run()
    assert not at.exception
    assert at.dataframe[0].value["Aspecto"].tolist() == ["Señal"]
    at.text_input(key="dashboard-search").set_value("inexistente").run()
    assert not at.exception
    assert len(at.dataframe) == 0
    at.button(key="dashboard-reset").click().run()
    assert not at.exception
    assert at.dataframe[0].value.shape[0] > 1
    at.selectbox(key="dashboard-scope").set_value("Historial · todas las revisiones").run()
    assert not at.exception
    assert at.dataframe[0].value["ID equipo"].unique().tolist() == ["A"]
