from datetime import date
from decimal import Decimal

import pandas as pd

from src.core import (
    choose_html_attachment,
    determine_key_column,
    determine_key_column_from_frame,
    maintenance_due_status,
    latest_equipment_control_values,
    infer_measurement_mode,
    validate_measurement_method,
    parse_measurement_coordinates,
    parse_sharepoint_attachment_url,
    snapshot_from_row,
    system_display_label,
    validate_html_file,
    validate_review,
    validate_review_signature,
)


def test_measurement_method_requires_one_of_two_paths():
    assert not validate_measurement_method(None).ok
    assert not validate_measurement_method("puntual", None).ok
    assert validate_measurement_method("puntual", 0).ok
    assert validate_measurement_method("puntual", 125.675).ok
    assert not validate_measurement_method("puntual", -1).ok
    assert not validate_measurement_method("puntual", float("nan")).ok
    assert not validate_measurement_method("temporal", graph_source="none").ok
    assert validate_measurement_method("temporal", graph_source="manual").ok
    assert validate_measurement_method("temporal", graph_source="sharepoint_link").ok


def test_old_revision_without_a_modality_remains_editable():
    assert infer_measurement_mode({"graph_source": "none"}) is None
    assert validate_measurement_method(None, allow_legacy_none=True).ok
    assert infer_measurement_mode({"graph_source": "manual"}) == "temporal"
    assert infer_measurement_mode({"point_flow_lps": 0}) == "puntual"
    assert infer_measurement_mode({"measurement_latitude": 9.9,
                                   "measurement_longitude": -84.1}) is None


def test_recover_last_defined_serials_from_revision_history():
    history = [
        {"equipment_type": "Ultrasónico", "equipment_serial": None,
         "transducer_serial": ""},
        {"equipment_type": "No definido", "equipment_serial": "EQ-NUEVO",
         "transducer_serial": None},
        {"equipment_type": "Electromagnético", "equipment_serial": "EQ-ANTERIOR",
         "transducer_serial": "TD-ANTERIOR"},
    ]
    assert latest_equipment_control_values(history) == {
        "equipment_type": "Ultrasónico",
        "equipment_serial": "EQ-NUEVO",
        "transducer_serial": "TD-ANTERIOR",
    }


def test_recover_serials_with_no_prior_reviews():
    assert latest_equipment_control_values([]) == {}


def test_system_filter_shows_code_and_name_from_catalog():
    assert system_display_label("MEA16") == "ME-A-16 — Potrerillos San Antonio"
    assert system_display_label("MAE16") == "ME-A-16 — Potrerillos San Antonio"
    assert system_display_label("ME-A-02") == "ME-A-02 — Guadalupe"
    assert system_display_label("ME-A-31") == "ME-A-31 — Puriscal"


def test_system_filter_preserves_names_from_geodatabase_and_unknown_codes():
    assert system_display_label("ME-A-16 POTRERILLOS SAN ANTONIO") == (
        "ME-A-16 — POTRERILLOS SAN ANTONIO"
    )
    assert system_display_label("ME-A-23") == "ME-A-23"
    assert system_display_label("Todos") == "Todos"
    assert system_display_label("Sistema sin código") == "Sistema sin código"


def test_determine_key_column_prefers_configured():
    cols = ["OBJECTID", "Código_Caudalimetro", "Nombre"]
    assert determine_key_column(cols, "Código_Caudalimetro") == "Código_Caudalimetro"


def test_determine_key_column_falls_back_to_objectid():
    assert determine_key_column(["Nombre", "OBJECTID"]) == "OBJECTID"


def test_validate_review_requires_rectification_equipment():
    result = validate_review(
        {
            "rectification_status": "Sí, con medición simultánea",
            "rectification_equipment": "",
            "is_ultrasonic": False,
            "measurement_quality": "Buena",
        }
    )
    assert not result.ok
    assert any("cuál equipo" in error for error in result.errors)


def test_sin_medicion_no_requiere_calidad():
    result = validate_review(
        {
            "rectification_status": "No se ha realizado",
            "rectification_equipment": "",
            "is_ultrasonic": False,
            "measurement_quality": None,
        }
    )
    assert result.ok


def test_sin_medicion_rechaza_calidad_no_aplicable():
    result = validate_review(
        {
            "rectification_status": "No se ha realizado",
            "rectification_equipment": "",
            "is_ultrasonic": False,
            "measurement_quality": "Buena",
        }
    )
    assert not result.ok
    assert any("no aplica" in error for error in result.errors)


def test_con_medicion_requiere_calidad():
    result = validate_review(
        {
            "rectification_status": "Sí, con medición simultánea",
            "rectification_equipment": "Equipo portátil 01",
            "is_ultrasonic": False,
            "measurement_quality": None,
        }
    )
    assert not result.ok
    assert any("calidad" in error for error in result.errors)


def test_firma_responsable_autorizado_y_fecha():
    assert validate_review_signature(
        "Allan Umaña Ortiz", date(2026, 10, 13), today=date(2026, 10, 13)
    ).ok
    assert not validate_review_signature(
        "Persona no autorizada", date(2026, 10, 13), today=date(2026, 10, 13)
    ).ok
    assert not validate_review_signature(
        "Allan Umaña Ortiz", None, today=date(2026, 10, 13)
    ).ok
    assert not validate_review_signature(
        "Allan Umaña Ortiz", date(2026, 10, 14), today=date(2026, 10, 13)
    ).ok


def test_validate_ultrasonic_dimensions():
    result = validate_review(
        {
            "rectification_status": "No se ha realizado",
            "rectification_equipment": "",
            "is_ultrasonic": True,
            "circumference_mm": 1000,
            "wall_thickness_mm": 0,
            "transducer_distance_mm": 120,
            "measurement_quality": "Excelente",
        }
    )
    assert not result.ok
    assert any("espesor" in error for error in result.errors)


def test_validate_html_file():
    assert validate_html_file("grafico.html", b"<html><body>ok</body></html>").ok
    assert not validate_html_file("grafico.csv", b"a,b").ok


def test_choose_html_attachment():
    attachments = [
        {"FileName": "foto.jpg", "TimeLastModified": "2026-01-01"},
        {"FileName": "uno.html", "TimeLastModified": "2026-01-02"},
        {"FileName": "dos.htm", "TimeLastModified": "2026-01-03"},
    ]
    assert choose_html_attachment(attachments)["FileName"] == "dos.htm"


def test_snapshot_normalizes_decimal():
    data = snapshot_from_row({"valor": Decimal("12.5")})
    assert data["valor"] == 12.5


def test_determine_key_column_from_frame_skips_empty_globalid():
    frame = pd.DataFrame(
        {
            "GlobalID": [None, None, None],
            "OBJECTID": [1, 2, 3],
            "Nombre": ["A", "B", "C"],
        }
    )
    assert determine_key_column_from_frame(frame, "Código_Caudalimetro") == "OBJECTID"


def test_determine_key_column_from_frame_prefers_populated_configured():
    frame = pd.DataFrame(
        {
            "Código_Caudalimetro": ["C-1", "C-2"],
            "OBJECTID": [1, 2],
        }
    )
    assert (
        determine_key_column_from_frame(frame, "Código_Caudalimetro")
        == "Código_Caudalimetro"
    )


def test_parse_sharepoint_attachment_url():
    parsed = parse_sharepoint_attachment_url(
        "https://intranetaya.sharepoint.com/sites/MejoramientodeSistemas769/"
        "Lists/Seguimiento%20de%20Deteccin%20de%20Fugas%20GAM/"
        "Attachments/2324/grafico_caudals.html?web=1"
    )
    assert parsed is not None
    assert parsed["item_id"] == 2324
    assert parsed["file_name"] == "grafico_caudals.html"


def test_parse_sharepoint_attachment_url_rejects_non_sharepoint():
    assert parse_sharepoint_attachment_url("https://example.com/file.html") is None


def test_parse_measurement_coordinates_accepts_wgs84():
    lat, lon, result = parse_measurement_coordinates("9.9281", "-84.0907")
    assert result.ok
    assert lat == 9.9281
    assert lon == -84.0907


def test_parse_measurement_coordinates_requires_both_values():
    lat, lon, result = parse_measurement_coordinates("9.9", "")
    assert lat is None
    assert lon is None
    assert not result.ok



def test_maintenance_status_green_before_due_date():
    kind, label = maintenance_due_status(
        date(2026, 1, 15),
        6,
        today=date(2026, 7, 15),
    )
    assert kind == "success"
    assert "Vigente" in label


def test_maintenance_status_red_after_due_date():
    kind, label = maintenance_due_status(
        date(2026, 1, 15),
        6,
        today=date(2026, 7, 16),
    )
    assert kind == "error"
    assert "Vencido" in label


def test_maintenance_status_no_aplica():
    kind, label = maintenance_due_status(
        None,
        6,
        applicable=False,
        today=date(2026, 7, 16),
    )
    assert kind == "info"
    assert "No aplica" in label


def test_maintenance_status_scada_failure_is_red():
    kind, label = maintenance_due_status(
        date(2026, 7, 1),
        1,
        condition_ok=False,
        today=date(2026, 7, 2),
    )
    assert kind == "error"
    assert "Requiere atención" in label
