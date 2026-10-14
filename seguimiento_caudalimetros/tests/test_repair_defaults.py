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
        assert at.checkbox(key=f"new-{field}").value is True

    assert at.checkbox(key="new-repair-spare-part").value is True
    assert any("todos los aspectos aparecen en rojo" in caption.value
               for caption in at.caption)


def test_pending_repair_can_be_marked_as_resolved(monkeypatch):
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    at.checkbox(key="new-repair_signal_pending").uncheck().run()
    assert not at.exception
    assert at.checkbox(key="new-repair_signal_pending").value is False
    assert at.checkbox(key="new-repair_calibration_pending").value is True
