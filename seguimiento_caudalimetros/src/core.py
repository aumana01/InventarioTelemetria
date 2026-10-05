from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

QUALITY_VALUES = ("Excelente", "Buena", "Regular", "Mala")
RECTIFICATION_VALUES = ("No se ha realizado", "Sí, con medición simultánea")
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

    if data.get("measurement_quality") not in QUALITY_VALUES:
        errors.append("Seleccione una calidad de medición válida.")

    return ValidationResult(ok=not errors, errors=tuple(errors))


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
