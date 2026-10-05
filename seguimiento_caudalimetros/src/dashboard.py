"""Dashboard tables and filters, independent of Streamlit and database connections."""
from __future__ import annotations

import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from src.core import add_months, maintenance_due_status, parse_optional_date

LOCAL_ZONE = ZoneInfo("America/Costa_Rica")
RED = "🔴 Rojo"
GREEN = "🟢 Verde"
GRAY = "⚪ No aplica"
PERIODS = ("Todo el historial", "Última semana", "Último mes", "Últimos 2 meses",
           "Último trimestre", "Último año", "Fecha específica", "Rango personalizado")
MAINTENANCE = (
    ("Cambio de gel", "maintenance_gel_date", 6, "maintenance_gel_applicable", True),
    ("Alineación y sujeción de transductores", "maintenance_transducers_alignment_date", 6,
     "maintenance_transducers_alignment_applicable", True),
    ("Descarga de datos internos", "maintenance_internal_download_date", 6,
     "maintenance_internal_download_applicable", True),
    ("Instalación simultánea con otro equipo", "maintenance_simultaneous_installation_date", 12, None, True),
    ("Limpieza del sensor de inserción", "maintenance_insertion_sensor_cleaning_date", 12, None, True),
    ("Limpieza de panel solar y gabinete", "maintenance_solar_panel_cleaning_date", 12,
     "maintenance_solar_panel_applicable", False),
    ("Funcionamiento en SCADA", "maintenance_scada_check_date", 1, None, True),
)
REPAIRS = (
    ("Señal", "repair_signal_pending"),
    ("Calibración", "repair_calibration_pending"),
    ("Energía", "repair_power_pending"),
    ("Cableado", "repair_wiring_pending"),
    ("Actualización de Software / Firmware", "repair_software_firmware_pending"),
    ("Visualización en Perspective", "repair_perspective_pending"),
    ("Vision Client CCO", "repair_vision_cco_pending"),
    ("Vision Client SCADA vr2", "repair_vision_scada_vr2_pending"),
    ("Descarga módulo de reportes", "repair_vision_reports_pending"),
    ("Repuesto particular", "repair_spare_part_required"),
    ("Sustitución temporal", "repair_temporary_replacement"),
    ("Sustitución permanente", "repair_permanent_replacement"),
)
META_COLUMNS = ["Registro", "ID equipo", "Sistema", "Equipo", "Tipo de equipo", "Serie",
                "Estado inventario", "Fecha de revisión", "Último mantenimiento", "Revisado por",
                "Calidad", "Rectificación", "Gráfico", "Observaciones", "Fallas"]
DETAIL_COLUMNS = META_COLUMNS + ["Categoría", "Aspecto", "Semáforo", "Estado",
                                 "Fecha del aspecto", "Vence", "Detalle"]
SUMMARY_COLUMNS = META_COLUMNS + ["Semáforo", "Estado", "Pendientes rojos", "Aspectos verdes",
                                  "No aplica", "Detalle de pendientes"]


def local_today() -> date:
    return datetime.now(LOCAL_ZONE).date()


def review_date(value: Any) -> date | None:
    """Convert timestamps to the user's date, rather than truncating UTC."""
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = pd.Timestamp(value)
        if pd.isna(parsed):
            return None
        if parsed.tzinfo is not None:
            parsed = parsed.tz_convert(LOCAL_ZONE)
        return parsed.date()
    except (ValueError, TypeError):
        return None


def period_bounds(period: str, today: date, specific: date | None = None,
                  custom: tuple[date, date] | None = None) -> tuple[date | None, date | None]:
    if period == "Todo el historial":
        return None, None
    if period == "Última semana":
        return today - timedelta(days=6), today
    months = {"Último mes": 1, "Últimos 2 meses": 2, "Último trimestre": 3, "Último año": 12}
    if period in months:
        return add_months(today, -months[period]), today
    if period == "Fecha específica" and specific:
        return specific, specific
    if period == "Rango personalizado" and custom:
        if custom[0] > custom[1]:
            raise ValueError("La fecha inicial debe ser anterior o igual a la final.")
        return custom
    raise ValueError("Seleccione una fecha o un rango completo.")


def _text(value: Any, default: str = "") -> str:
    if value is None or (not isinstance(value, (dict, list)) and pd.isna(value)):
        return default
    return str(value).strip() or default


def _first(row: Mapping[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        value = _text(row.get(name))
        if value:
            return value
    return default


def _type(review: Mapping[str, Any], meter: Mapping[str, Any]) -> str:
    value = _text(review.get("equipment_type"))
    if value and value != "No definido":
        return value
    if review.get("is_ultrasonic"):
        return "Ultrasónico"
    return _first(meter, "Tipo de equipo", "Tipo", "TIPO", "TIPO_EQUIPO", default="No definido")


def _graph(review: Mapping[str, Any]) -> str:
    if review.get("graph_storage_path"):
        return "Disponible"
    if review.get("graph_source") == "sharepoint_link":
        return "Pendiente de importación"
    return "Sin gráfico"


def _review_order(review: Mapping[str, Any]) -> tuple[int, str]:
    stamp = pd.to_datetime(review.get("reviewed_at"), utc=True, errors="coerce")
    return (int(stamp.value) if pd.notna(stamp) else -1, str(review.get("id") or ""))


def build_dashboard_tables(inventory: Iterable[Mapping[str, Any]], reviews: Iterable[Mapping[str, Any]],
                           *, history: bool = False, today: date | None = None
                           ) -> tuple[pd.DataFrame, pd.DataFrame]:
    today = today or local_today()
    meters = {_text(m.get("ID equipo")): dict(m) for m in inventory}
    # Latest is chosen BEFORE applying date filters, so old solved issues do not reappear.
    ordered = sorted(reviews, key=_review_order, reverse=True)
    chosen: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for review in ordered:
        key = _text(review.get("equipment_key"))
        if history or key not in seen:
            chosen.append(review)
        seen.add(key)
    if not history:
        chosen.extend({"equipment_key": key} for key in meters if key not in seen)

    summary_rows, detail_rows = [], []
    for index, review in enumerate(chosen):
        key = _text(review.get("equipment_key"))
        snapshot = review.get("geodatabase_snapshot") or {}
        meter = meters.get(key, {})
        has_review = bool(review.get("id") or review.get("reviewed_at"))
        meta = {
            "Registro": _text(review.get("id"), f"sin-revision-{index}"),
            "ID equipo": key,
            "Sistema": _first(meter, "Sistema", default=_first(snapshot, "OBSERVACIO", "OBSERVACION",
                              "Sistema_De_Abastecimiento", "Sistema", "SISTEMA", default="Sin sistema")),
            "Equipo": _first(meter, "Equipo", default=_first(snapshot, "DESCRIPCIO", "DESCRIPCION",
                             "Nombre", default=_text(review.get("equipment_label"), key))),
            "Tipo de equipo": _type(review, meter or snapshot),
            "Serie": _text(review.get("equipment_serial"), "Sin serie"),
            "Estado inventario": _first(meter, "Estado inventario", default="Sin dato"),
            "Fecha de revisión": review_date(review.get("reviewed_at")),
            "Último mantenimiento": parse_optional_date(review.get("last_maintenance_date")),
            "Revisado por": _text(review.get("reviewed_by"), "Sin responsable"),
            "Calidad": _text(review.get("measurement_quality"), "Sin dato"),
            "Rectificación": _text(review.get("rectification_status"), "Sin dato"),
            "Gráfico": _graph(review) if has_review else "Sin gráfico",
            "Observaciones": _text(review.get("notes")),
            "Fallas": _text(review.get("failures")),
        }
        aspects = []

        def append(category, label, semaphore, state, aspect_date=None, due=None, detail=""):
            aspects.append({**meta, "Categoría": category, "Aspecto": label, "Semáforo": semaphore,
                            "Estado": state, "Fecha del aspecto": aspect_date, "Vence": due, "Detalle": detail})

        if not has_review:
            append("Revisión", "Revisión de equipo", RED, "Sin revisión")
        else:
            for label, field, months, applies_field, default in MAINTENANCE:
                applies = bool(review.get(applies_field, default)) if applies_field else True
                if field == "maintenance_insertion_sensor_cleaning_date":
                    # Match the existing ficha's applicability rule.
                    applies = review.get("equipment_type") == "Inserción"
                ok = review.get("maintenance_scada_working") is True if field == "maintenance_scada_check_date" else True
                kind, message = maintenance_due_status(review.get(field), months, applicable=applies,
                                                        condition_ok=ok, today=today)
                stamp = parse_optional_date(review.get(field))
                append("Mantenimiento", label, {"error": RED, "success": GREEN, "info": GRAY}[kind],
                       message[2:].strip(), stamp if applies else None,
                       add_months(stamp, months) if stamp and applies else None)
            for label, field in REPAIRS:
                pending = bool(review.get(field, False))
                append("Reparación", label, RED if pending else GREEN,
                       "Pendiente" if pending else "Sin pendiente", meta["Fecha de revisión"],
                       detail=_text(review.get("repair_spare_part_detail")) if field == "repair_spare_part_required" else "")
            quality_ok = review.get("measurement_quality") in {"Excelente", "Buena"}
            append("Control general", "Calidad de medición", GREEN if quality_ok else RED,
                   meta["Calidad"], meta["Fecha de revisión"])
            rectified = review.get("rectification_status") == "Sí, con medición simultánea"
            append("Control general", "Rectificación", GREEN if rectified else RED,
                   meta["Rectificación"], meta["Fecha de revisión"])

        red = [a for a in aspects if a["Semáforo"] == RED]
        green = sum(a["Semáforo"] == GREEN for a in aspects)
        summary_rows.append({**meta, "Semáforo": RED if red else GREEN,
                             "Estado": "Sin revisión" if not has_review else ("Con pendientes" if red else "Sin pendientes"),
                             "Pendientes rojos": len(red), "Aspectos verdes": green,
                             "No aplica": sum(a["Semáforo"] == GRAY for a in aspects),
                             "Detalle de pendientes": "; ".join(f"{a['Aspecto']}: {a['Estado']}" for a in red)})
        detail_rows.extend(aspects)
    return pd.DataFrame(summary_rows, columns=SUMMARY_COLUMNS), pd.DataFrame(detail_rows, columns=DETAIL_COLUMNS)


def normalized_search(value: Any) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(value)).lower()
                   if not unicodedata.combining(c) and c.isalnum())


def filter_dashboard(frame: pd.DataFrame, *, selections: Mapping[str, list[str]] | None = None,
                     start: date | None = None, end: date | None = None,
                     date_column: str = "Fecha de revisión", include_undated: bool = False,
                     query: str = "", only_unreviewed: bool = False) -> pd.DataFrame:
    result = frame.copy()
    for column, values in (selections or {}).items():
        if values:
            result = result[result[column].isin(values)]
    if start is not None or end is not None:
        def matches(value):
            stamp = parse_optional_date(value)
            if stamp is None:
                return include_undated
            return (start is None or stamp >= start) and (end is None or stamp <= end)
        result = result[result[date_column].map(matches).astype(bool)]
    if only_unreviewed:
        result = result[result["Fecha de revisión"].isna()]
    terms = [normalized_search(word) for word in query.split() if normalized_search(word)]
    if terms:
        text_columns = [c for c in result.columns if c != "Registro"]
        haystack = result[text_columns].astype(str).agg(" ".join, axis=1).map(normalized_search)
        result = result[haystack.map(lambda value: all(term in value for term in terms)).astype(bool)]
    return result.reset_index(drop=True)


def style_status_row(row: pd.Series) -> list[str]:
    colors = {RED: "background-color: #fde8e7; color: #75201d;",
              GREEN: "background-color: #e3f4e9; color: #155a32;",
              GRAY: "background-color: #edf0f4; color: #394553;"}
    return [colors.get(row.get("Semáforo"), "")] * len(row)


def export_csv(frame: pd.DataFrame) -> bytes:
    # Keep spreadsheet applications from interpreting user text as formulas.
    result = frame.drop(columns=["Registro"], errors="ignore").copy()
    for column in result.select_dtypes(include=["object", "string"]).columns:
        result[column] = result[column].map(lambda v: "'" + v if isinstance(v, str) and
                                          v.lstrip().startswith(("=", "+", "-", "@")) else v)
    return result.to_csv(index=False).encode("utf-8-sig")
