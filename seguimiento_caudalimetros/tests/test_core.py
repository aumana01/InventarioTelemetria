from decimal import Decimal

from src.core import (
    choose_html_attachment,
    determine_key_column,
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
