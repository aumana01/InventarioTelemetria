from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"

REPAIR_FIELDS = (
    "repair_signal_pending",
    "repair_calibration_pending",
    "repair_power_pending",
    "repair_wiring_pending",
    "repair_software_firmware_pending",
    "repair_perspective_pending",
    "repair_vision_cco_pending",
    "repair_vision_scada_vr2_pending",
    "repair_vision_reports_pending",
    "repair_temporary_replacement",
    "repair_permanent_replacement",
)


def test_new_review_starts_with_all_repairs_pending(monkeypatch):
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception

    for field in REPAIR_FIELDS:
        assert at.checkbox(key=f"new-DEMO-001-{field}").value is True

    assert at.checkbox(key="new-DEMO-001-repair-spare-part").value is True
    assert any("todos los aspectos inician pendientes" in caption.value
               for caption in at.caption)


def test_pending_repair_can_be_marked_as_resolved(monkeypatch):
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    at.checkbox(key="new-DEMO-001-repair_signal_pending").uncheck().run()
    assert not at.exception
    assert at.checkbox(key="new-DEMO-001-repair_signal_pending").value is False
    assert at.checkbox(key="new-DEMO-001-repair_calibration_pending").value is True


def test_comparative_measurement_routes_are_mutually_exclusive(monkeypatch):
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    method = next(item for item in at.radio if item.label == "Modalidad de medición")
    assert method.value is None

    method.set_value("puntual").run()
    assert not at.exception
    assert any(item.label == "Caudal medido (L/s)" for item in at.number_input)
    assert any(item.label == "Observaciones de la medición puntual" for item in at.text_area)
    assert not any(item.label == "Origen del gráfico" for item in at.radio)

    method = next(item for item in at.radio if item.label == "Modalidad de medición")
    method.set_value("temporal").run()
    assert not at.exception
    assert any(item.label == "Origen del gráfico" for item in at.radio)
    assert not any(item.label == "Caudal medido (L/s)" for item in at.number_input)



def test_equipment_switch_drops_unsaved_repair_changes(monkeypatch):
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    at.checkbox(key="new-DEMO-001-repair_signal_pending").uncheck().run()
    assert not at.exception

    # El selector exige confirmar el cambio para no perder datos sin guardar.
    at.sidebar.selectbox(key="meter_selector_index").set_value(1).run()
    assert not at.exception
    at.button(key="confirm-equipment-change").click().run()
    assert not at.exception
    assert at.checkbox(key="new-DEMO-002-repair_signal_pending").value is True

    at.sidebar.selectbox(key="meter_selector_index").set_value(0).run()
    assert not at.exception
    at.button(key="confirm-equipment-change").click().run()
    assert not at.exception
    assert at.checkbox(key="new-DEMO-001-repair_signal_pending").value is True
