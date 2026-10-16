from __future__ import annotations

import calendar
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlparse

MEASUREMENT_MODES = ("puntual", "temporal")
MEASUREMENT_MODE_LABELS = {
    "puntual": "Medición puntual de caudal (L/s)",
    "temporal": "Medición temporal con gráfico comparativo",
}


def infer_measurement_mode(review: Mapping[str, Any]) -> str | None:
    """Conserva la compatibilidad de las fichas anteriores a la migración."""
    value = str(review.get("measurement_method") or "").strip()
    if value in MEASUREMENT_MODES:
        return value
    if review.get("point_flow_lps") is not None:
        return "puntual"
    if review.get("graph_source") not in (None, "", "none"):
        return "temporal"
    # Coordenadas históricas solas no prueban que exista caudal puntual.
    # Se mantiene la modalidad sin clasificar hasta que el usuario la indique.
    return None


def validate_measurement_method(
    mode: str | None,
    point_flow_lps: float | int | None = None,
    graph_source: str = "none",
    *,
    allow_legacy_none: bool = False,
) -> "ValidationResult":
    """Solo una modalidad; caudal puntual real o gráfico de medición temporal."""
    errors: list[str] = []
    if mode is None and allow_legacy_none:
        return ValidationResult(ok=True)
    if mode not in MEASUREMENT_MODES:
        errors.append("Seleccione medición puntual o medición temporal con gráfico.")
    elif mode == "puntual":
        try:
            flow = float(point_flow_lps) if point_flow_lps is not None else None
        except (TypeError, ValueError):
            flow = None
        if flow is None or not math.isfinite(flow) or flow < 0:
            errors.append("Indique un caudal puntual válido en L/s (cero o mayor).")
    elif graph_source not in ("manual", "sharepoint_link", "sharepoint"):
        errors.append("Para la medición temporal debe adjuntar un HTML o vínculo SharePoint.")
    return ValidationResult(ok=not errors, errors=tuple(errors))


QUALITY_VALUES = ("Excelente", "Buena", "Regular", "Mala")
RECTIFICATION_VALUES = ("No se ha realizado", "Sí, con medición simultánea")
SYSTEM_NAMES_BY_CODE = {
    1: "Tres Ríos",
    2: "Guadalupe",
    3: "El Llano",
    4: "Los Sitios",
    5: "Salitral",
    6: "San Juan de Dios",
    7: "San Antonio Escazú",
    8: "Los Cuadros",
    9: "Alajuelita",
    10: "Mata de Plátano",
    11: "Guatuso Patarrá",
    12: "Quitirrisí",
    13: "San Jerónimo Moravia",
    14: "San Rafael",
    15: "San Pablo",
    16: "Potrerillos San Antonio",
    17: "La Valencia",
    18: "Lámparas",
    19: "Puente de Mulas",
    20: "Padre Carazo",
    21: "Chiverrales",
    22: "Pizote",
    24: "Matinilla",
    25: "Sur Escazú",
    26: "Ticufres Q Honda",
    27: "El Guarco",
    28: "Vista de Mar",
    29: "Lajas",
    30: "Jericó",
    31: "Puriscal",
}


def system_display_label(value: str) -> str:
    """Muestra el nombre de sistema junto al código, sin cambiar el valor filtrado."""
    raw = str(value or "").strip()
    if not raw or raw == "Todos":
        return raw
    match = re.match(r"^(?:ME[-\s]?A|MAE)[-\s]*0?(\d{1,2})(?!\d)", raw, flags=re.I)
    if not match:
        return raw
    number = int(match.group(1))
    name = raw[match.end():].strip(" -—:·") or SYSTEM_NAMES_BY_CODE.get(number, "")
    return f"ME-A-{number:02d} — {name}" if name else raw


AUTHORIZED_REVIEWERS = (
    "Allan Umaña Ortiz",
    "Andrey Arrieta Mendez",
    "Jose David Soto Flores",
    "Valerie Chavez Ruphuy",
    "Manuel Jimenez Rivera",
    "Jefferson Mayorga Cerdas",
    "Alexander Vargas Guevara",
)
EQUIPMENT_TYPE_VALUES = (
    "No definido",
    "Ultrasónico",
    "Electromagnético",
    "Canal Abierto",
    "Inserción",
)
MAX_HTML_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...] = ()


def determine_key_column(columns: Iterable[str], preferred: str | None = None) -> str:
    cols = [str(c) for c in columns]
    if preferred and preferred in cols:
        return preferred

    normalized = {re.sub(r"[^a-z0-9]", "", c.lower()): c for c in cols}
    candidates = (
        "codigocaudalimetro",
        "codigomedidor",
        "codigo",
        "assetid",
        "globalid",
        "objectid",
        "fid",
        "id",
    )
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    if not cols:
        raise ValueError("La consulta SQL no devolvió columnas.")
    return cols[0]


def determine_key_column_from_frame(data, preferred: str | None = None) -> str:
    """Elige una clave utilizable considerando nombres y datos realmente poblados."""
    cols = [str(c) for c in data.columns]
    if not cols:
        raise ValueError("La consulta SQL no devolvió columnas.")

    normalized = {re.sub(r"[^a-z0-9]", "", c.lower()): c for c in cols}
    ordered: list[str] = []

    if preferred:
        if preferred in cols:
            ordered.append(preferred)
        preferred_norm = re.sub(r"[^a-z0-9]", "", preferred.lower())
        mapped = normalized.get(preferred_norm)
        if mapped and mapped not in ordered:
            ordered.append(mapped)

    for candidate in (
        "codigocaudalimetro",
        "codigomedidor",
        "codigo",
        "assetid",
        "globalid",
        "objectid",
        "fid",
        "id",
    ):
        mapped = normalized.get(candidate)
        if mapped and mapped not in ordered:
            ordered.append(mapped)

    def stats(column: str) -> tuple[int, int]:
        series = data[column]
        valid = series.notna()
        if valid.any():
            text_values = series.astype(str).str.strip().str.lower()
            valid = valid & ~text_values.isin({"", "nan", "none", "null"})
        nonempty = int(valid.sum())
        unique = int(series[valid].astype(str).nunique(dropna=True)) if nonempty else 0
        return nonempty, unique

    # Preferimos una columna candidata completa y única.
    for column in ordered:
        nonempty, unique = stats(column)
        if nonempty == len(data) and unique == nonempty and nonempty > 0:
            return column

    # Si ninguna candidata está completa, usamos la candidata con más valores únicos,
    # siempre que tenga al menos un dato.
    ranked: list[tuple[int, int, int, str]] = []
    for position, column in enumerate(ordered):
        nonempty, unique = stats(column)
        if nonempty > 0:
            ranked.append((unique, nonempty, -position, column))
    if ranked:
        return max(ranked)[3]

    # Último recurso: cualquier columna totalmente poblada y única.
    fallback: list[tuple[int, str]] = []
    for column in cols:
        nonempty, unique = stats(column)
        if nonempty == len(data) and unique == nonempty and nonempty > 0:
            fallback.append((unique, column))
    if fallback:
        return fallback[0][1]

    raise ValueError(
        "No se encontró una columna identificadora con valores utilizables. "
        "Revise Código_Caudalimetro, GlobalID, OBJECTID u otra clave del inventario."
    )


def normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item"):
        try:
            return normalize_value(value.item())
        except Exception:
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, Mapping):
        return {str(k): normalize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [normalize_value(v) for v in value]
    return value


def snapshot_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(k): normalize_value(v) for k, v in row.items()}


def parse_optional_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return None


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + int(months)
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def maintenance_due_status(
    last_date: Any,
    interval_months: int,
    *,
    applicable: bool = True,
    condition_ok: bool = True,
    today: date | None = None,
) -> tuple[str, str]:
    """Devuelve (kind, texto) para el semáforo de mantenimiento."""
    if not applicable:
        return "info", "⚪ No aplica"
    if not condition_ok:
        return "error", "🔴 Requiere atención"

    parsed = parse_optional_date(last_date)
    if parsed is None:
        return "error", "🔴 Sin fecha"

    reference = today or date.today()
    due = add_months(parsed, interval_months)
    if reference > due:
        return "error", f"🔴 Vencido desde {due.strftime('%d/%m/%Y')}"
    return "success", f"🟢 Vigente hasta {due.strftime('%d/%m/%Y')}"


def review_prefill_values(
    latest_review: Mapping[str, Any] | None,
    equipment_defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepara la nueva ficha desde la última revisión del mismo caudalímetro.

    Mantiene False, None y fechas exactamente como fueron guardados; solo
    recupera de revisiones previas los identificadores técnicos ausentes.
    No incluye datos de la firma de la revisión nueva.
    """
    previous = dict(latest_review or {})
    for field in ("equipment_type", "equipment_serial", "transducer_serial"):
        old_value = previous.get(field)
        missing = old_value is None or str(old_value).strip() == ""
        if field == "equipment_type" and old_value == "No definido":
            missing = True
        if missing and (equipment_defaults or {}).get(field):
            previous[field] = equipment_defaults[field]
    return previous


def latest_equipment_control_values(
    reviews: Iterable[Mapping[str, Any]],
    current: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Recupera para el mismo caudalímetro cada último dato no vacío.

    Las revisiones deben estar ordenadas de más reciente a más antigua.
    Una ficha posterior sin número de serie no borra el dato persistente.
    """
    values = dict(current or {})
    keys = ("equipment_type", "equipment_serial", "transducer_serial")
    for review in reviews:
        for key in keys:
            if values.get(key):
                continue
            value = str(review.get(key) or "").strip()
            if not value or (key == "equipment_type" and value == "No definido"):
                continue
            values[key] = value
        if all(values.get(key) for key in keys):
            break
    return {key: str(values[key]) for key in keys if values.get(key)}


def validate_review(data: Mapping[str, Any]) -> ValidationResult:
    errors: list[str] = []
    rectification = data.get("rectification_status")
    if rectification not in RECTIFICATION_VALUES:
        errors.append("Seleccione el estado de rectificación.")
    if rectification == "Sí, con medición simultánea" and not str(
        data.get("rectification_equipment") or ""
    ).strip():
        errors.append("Indique con cuál equipo se realizó la rectificación simultánea.")

    if data.get("is_ultrasonic"):
        labels = {
            "circumference_mm": "circunferencia",
            "wall_thickness_mm": "espesor",
            "transducer_distance_mm": "distancia de transductores",
        }
        for key, label in labels.items():
            try:
                value = float(data.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value <= 0:
                errors.append(f"La {label} debe ser mayor que cero para un equipo ultrasónico.")

    quality = data.get("measurement_quality")
    if rectification == "Sí, con medición simultánea":
        if quality not in QUALITY_VALUES:
            errors.append("Seleccione una calidad de medición válida.")
    elif rectification == "No se ha realizado" and quality not in (None, ""):
        errors.append("La calidad de medición no aplica si no hubo medición simultánea.")

    return ValidationResult(ok=not errors, errors=tuple(errors))


def validate_review_signature(
    reviewed_by: str | None,
    signed_date: date | None,
    *,
    today: date | None = None,
) -> ValidationResult:
    """Valida responsable autorizado y fecha de firma de la revisión del equipo."""
    errors: list[str] = []
    if reviewed_by not in AUTHORIZED_REVIEWERS:
        errors.append("Seleccione una persona autorizada para firmar la revisión.")
    if not isinstance(signed_date, date):
        errors.append("Indique la fecha de revisión del equipo.")
    elif signed_date > (today or date.today()):
        errors.append("La fecha de revisión no puede ser futura.")
    return ValidationResult(ok=not errors, errors=tuple(errors))



def parse_sharepoint_attachment_url(url: str) -> dict[str, Any] | None:
    """Extrae ID de elemento y nombre de archivo desde un adjunto estándar de SharePoint."""
    value = str(url or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https" or not parsed.netloc.lower().endswith(".sharepoint.com"):
        return None
    match = re.search(r"/Attachments/(\d+)/([^/?#]+)", parsed.path, flags=re.IGNORECASE)
    if not match:
        return {
            "url": value,
            "item_id": None,
            "file_name": None,
        }
    return {
        "url": value,
        "item_id": int(match.group(1)),
        "file_name": unquote(match.group(2)),
    }


def parse_measurement_coordinates(
    latitude: str | float | int | None,
    longitude: str | float | int | None,
) -> tuple[float | None, float | None, ValidationResult]:
    lat_raw = "" if latitude is None else str(latitude).strip().replace(",", ".")
    lon_raw = "" if longitude is None else str(longitude).strip().replace(",", ".")

    if not lat_raw and not lon_raw:
        return None, None, ValidationResult(ok=True)

    errors: list[str] = []
    if not lat_raw or not lon_raw:
        errors.append("Ingrese tanto la latitud como la longitud del punto de medición.")
        return None, None, ValidationResult(ok=False, errors=tuple(errors))

    try:
        lat = float(lat_raw)
    except ValueError:
        lat = None
        errors.append("La latitud del punto de medición no es válida.")

    try:
        lon = float(lon_raw)
    except ValueError:
        lon = None
        errors.append("La longitud del punto de medición no es válida.")

    if lat is not None and not (-90 <= lat <= 90):
        errors.append("La latitud debe estar entre -90 y 90.")
    if lon is not None and not (-180 <= lon <= 180):
        errors.append("La longitud debe estar entre -180 y 180.")

    return lat, lon, ValidationResult(ok=not errors, errors=tuple(errors))

def safe_filename(filename: str) -> str:
    name = Path(filename or "grafico.html").name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return stem or "grafico.html"


def validate_html_file(filename: str, content: bytes) -> ValidationResult:
    errors: list[str] = []
    if Path(filename).suffix.lower() not in {".html", ".htm"}:
        errors.append("El archivo debe tener extensión .html o .htm.")
    if not content:
        errors.append("El archivo HTML está vacío.")
    if len(content) > MAX_HTML_BYTES:
        errors.append("El archivo HTML supera el límite de 10 MB.")
    if content and b"<" not in content[: min(len(content), 200_000)]:
        errors.append("El contenido no parece corresponder a un documento HTML.")
    return ValidationResult(ok=not errors, errors=tuple(errors))


def choose_html_attachment(attachments: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    html_files = []
    for item in attachments:
        filename = str(item.get("FileName") or item.get("Name") or "")
        if Path(filename).suffix.lower() in {".html", ".htm"}:
            html_files.append(item)
    if not html_files:
        return None
    return sorted(
        html_files,
        key=lambda x: str(x.get("TimeLastModified") or x.get("FileName") or ""),
        reverse=True,
    )[0]
