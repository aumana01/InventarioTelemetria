from decimal import Decimal

import pandas as pd

from src.core import (
    choose_html_attachment,
    determine_key_column,
    determine_key_column_from_frame,
    parse_measurement_coordinates,
    parse_sharepoint_attachment_url,
    snapshot_from_row,
    validate_html_file,
    validate_review,
)


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
