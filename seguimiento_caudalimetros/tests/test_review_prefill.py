"""Prueba integrada de precarga por caudalímetro usando un Supabase simulado."""
from dataclasses import replace
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.config import Settings
import src.supabase_repository as repository_module
from src.supabase_repository import SupabaseMeterRepository, SupabaseReviewRepository


APP = Path(__file__).resolve().parents[1] / "app.py"


def test_switching_equipment_prefills_latest_saved_review(monkeypatch):
    fake_settings = replace(
        Settings.load(),
        demo_mode=False,
        data_source="supabase",
        supabase_url="https://prefill-test.supabase.co",
        supabase_key="test-key",
        app_password="",
    )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: fake_settings))
    monkeypatch.setattr(repository_module, "_client", lambda _settings: object())

    meters = pd.DataFrame([
        {"Código_Caudalimetro": "FM-A", "DESCRIPCIO": "Equipo A",
         "OBSERVACIO": "MAE16", "LONGITUD": -84.1, "LATITUD": 9.9},
        {"Código_Caudalimetro": "FM-B", "DESCRIPCIO": "Equipo B",
         "OBSERVACIO": "MAE19", "LONGITUD": -84.2, "LATITUD": 9.8},
    ])
    monkeypatch.setattr(SupabaseMeterRepository, "load_meters", lambda self: meters)

    reviews = {
        "FM-A": {
            "id": "revision-a", "equipment_key": "FM-A", "equipment_type": "Ultrasónico",
            "equipment_serial": "EQ-A", "transducer_serial": "TR-A",
            "circumference_mm": 1000, "wall_thickness_mm": 10,
            "transducer_distance_mm": 200, "maintenance_gel_date": "2026-09-20",
            "maintenance_scada_working": True, "repair_signal_pending": False,
            "repair_power_pending": True, "repair_spare_part_required": False,
            "measurement_method": "puntual", "point_flow_lps": 45.5,
            "point_observations": "Toma de campo", "notes": "Equipo con seguimiento",
            "review_date": "2026-10-10", "reviewed_by": "Allan Umaña Ortiz",
        },
        "FM-B": {
            "id": "revision-b", "equipment_key": "FM-B",
            "equipment_type": "Electromagnético", "equipment_serial": "EQ-B",
            "electromagnetic_diameter": 300, "repair_signal_pending": True,
            "repair_power_pending": False, "repair_spare_part_required": False,
            "measurement_method": "puntual", "point_flow_lps": 18.0,
            "review_date": "2026-10-11",
        },
    }
    monkeypatch.setattr(
        SupabaseReviewRepository, "latest_review",
        lambda self, key: reviews.get(key),
    )
    monkeypatch.setattr(
        SupabaseReviewRepository, "equipment_control_defaults",
        lambda self, key: {
            field: reviews[key][field]
            for field in ("equipment_type", "equipment_serial", "transducer_serial")
            if key in reviews and reviews[key].get(field)
        },
    )

    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    assert at.text_input(key="new-FM-A-equipment-serial").value == "EQ-A"
    assert at.checkbox(key="new-FM-A-repair_signal_pending").value is False
    assert at.checkbox(key="new-FM-A-repair_power_pending").value is True
    assert at.date_input(key="new-FM-A-maintenance-gel").value.isoformat() == "2026-09-20"
    assert at.radio(key="new-measurement-mode-FM-A").value == "puntual"
    assert at.number_input(key="new-point-flow-FM-A").value == 45.5
    assert at.text_area(key="new-FM-A-notes").value == "Equipo con seguimiento"
    assert at.selectbox(key="new-FM-A-reviewed-by").value == ""

    at.sidebar.selectbox(key="meter_selector_index").set_value(1).run()
    assert not at.exception
    at.button(key="confirm-equipment-change").click().run()
    assert not at.exception
    assert at.text_input(key="new-FM-B-equipment-serial").value == "EQ-B"
    assert at.checkbox(key="new-FM-B-repair_signal_pending").value is True
    assert at.checkbox(key="new-FM-B-repair_power_pending").value is False
    assert at.number_input(key="new-point-flow-FM-B").value == 18.0
