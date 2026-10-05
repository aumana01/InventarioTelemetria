from __future__ import annotations

import hmac
import html
import re
from datetime import date
from pathlib import Path
from typing import Any

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src.config import Settings
from src.core import (
    QUALITY_VALUES,
    RECTIFICATION_VALUES,
    determine_key_column,
    determine_key_column_from_frame,
    maintenance_due_status,
    parse_measurement_coordinates,
    parse_sharepoint_attachment_url,
    snapshot_from_row,
    validate_html_file,
    validate_review,
)
from src.graph_renderer import render_stored_graph
from src.sql_repository import SqlMeterRepository
from src.supabase_repository import SupabaseMeterRepository, SupabaseReviewRepository
from src.ui import load_css, readonly_snapshot, review_summary, status_badge

BASE_DIR = Path(__file__).resolve().parent

st.set_page_config(
    page_title="Seguimiento de Caudalímetros",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded",
)
load_css(BASE_DIR / "assets" / "styles.css")

settings = Settings.load()


def password_gate() -> None:
    if not settings.app_password:
        return
    if st.session_state.get("authenticated"):
        return

    st.title("Seguimiento de Caudalímetros")
    st.caption("Acceso restringido")
    password = st.text_input("Contraseña de acceso", type="password")
    if st.button("Ingresar", type="primary"):
        if hmac.compare_digest(password, settings.app_password):
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Contraseña incorrecta.")
    st.stop()


password_gate()


def demo_meters() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Código_Caudalimetro": "DEMO-001",
                "Nombre": "Caudalímetro demostración Guadalupe",
                "Sistema": "ME-A-02 Guadalupe",
                "Tipo": "Electromagnético",
                "Diámetro_mm": 250,
                "Estado": "Operativo",
                "LONGITUD": -84.0648,
                "LATITUD": 9.9524,
                "EPSG_WGS84": 4326,
            },
            {
                "Código_Caudalimetro": "DEMO-002",
                "Nombre": "Caudalímetro demostración La Valencia",
                "Sistema": "ME-A-17 La Valencia",
                "Tipo": "Ultrasónico",
                "Diámetro_mm": 400,
                "Estado": "Operativo",
                "LONGITUD": -84.1113,
                "LATITUD": 9.9711,
                "EPSG_WGS84": 4326,
            },
            {
                "Código_Caudalimetro": "DEMO-003",
                "Nombre": "Caudalímetro demostración Puente Mulas",
                "Sistema": "ME-A-19 Puente Mulas",
                "Tipo": "Electromagnético",
                "Diámetro_mm": 600,
                "Estado": "Revisión",
                "LONGITUD": -84.1440,
                "LATITUD": 9.9182,
                "EPSG_WGS84": 4326,
            },
        ]
    )


@st.cache_data(ttl=300, show_spinner=False)
def load_meters(current_settings: Settings) -> pd.DataFrame:
    if current_settings.demo_mode:
        return demo_meters()

    source = current_settings.meter_data_source
    if source == "supabase":
        if not current_settings.supabase_configured:
            raise RuntimeError(
                "La fuente de caudalímetros es Supabase, pero Supabase no está configurado."
            )
        return SupabaseMeterRepository(current_settings).load_meters()

    if source == "sql":
        if not current_settings.sql_configured:
            raise RuntimeError(
                "La fuente de caudalímetros es SQL, pero no hay credenciales SQL configuradas."
            )
        return SqlMeterRepository(current_settings).load_meters()

    raise RuntimeError(f"Fuente de datos no soportada: {source}")


@st.cache_resource
def get_supabase_meter_repo(current_settings: Settings) -> SupabaseMeterRepository:
    return SupabaseMeterRepository(current_settings)


@st.cache_resource
def get_supabase_repo(current_settings: Settings) -> SupabaseReviewRepository:
    return SupabaseReviewRepository(current_settings)


def first_nonempty(row: pd.Series, candidates: list[str]) -> str:
    for column in candidates:
        if column in row.index:
            value = row.get(column)
            if pd.notna(value) and str(value).strip():
                return str(value).strip()
    return ""


def normalized_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def find_column(columns: list[str], candidates: list[str]) -> str | None:
    by_normalized = {normalized_header(column): column for column in columns}
    for candidate in candidates:
        found = by_normalized.get(normalized_header(candidate))
        if found:
            return found
    return None


def meter_system(row: pd.Series, system_column: str | None = None) -> str:
    if system_column and system_column in row.index:
        value = row.get(system_column)
        if pd.notna(value) and str(value).strip():
            return str(value).strip()
    return first_nonempty(
        row,
        [
            "OBSERVACIO",
            "OBSERVACION",
            "Observacio",
            "Observacion",
            "Sistema_De_Abastecimiento",
            "SISTEMA_DE_ABASTECIMIENTO",
            "Sistema de Abastecimiento",
            "Código_Sistema",
            "Codigo_Sistema",
            "CODIGO_SISTEMA",
            "Sistema",
            "SISTEMA",
            "NOMBRE_SISTEMA",
            "Nombre_Sistema",
        ],
    )


def meter_name(row: pd.Series, name_column: str | None = None) -> str:
    if name_column and name_column in row.index:
        value = row.get(name_column)
        if pd.notna(value) and str(value).strip():
            return str(value).strip()
    return first_nonempty(
        row,
        [
            "DESCRIPCIO",
            "DESCRIPCION",
            "Descripcion",
            "Descripción",
            "Nombre_Caudalimetro",
            "NOMBRE_CAUDALIMETRO",
            "Nombre del Caudalímetro",
            "Nombre_Equipo",
            "NOMBRE_EQUIPO",
            "Nombre",
            "NOMBRE",
            "DESCRIPCION",
            "Descripción",
            "Descripcion",
            "UBICACION",
            "Ubicación",
        ],
    )


def meter_label(
    row: pd.Series,
    key_column: str,
    system_column: str | None = None,
    name_column: str | None = None,
) -> str:
    system = meter_system(row, system_column)
    name = meter_name(row, name_column)
    parts = [value for value in [system, name] if value]
    if parts:
        return " — ".join(parts)
    return f"Caudalímetro (ID interno {row.get(key_column, '')})"


def search_normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def meter_matches_search(
    row: pd.Series,
    query: str,
    system_column: str | None,
    name_column: str | None,
) -> bool:
    query = str(query or "").strip()
    if not query:
        return True
    system = meter_system(row, system_column)
    name = meter_name(row, name_column)
    plain_query = query.lower()
    combined = f"{system} {name}".lower()
    if plain_query in combined:
        return True
    compact_query = search_normalized(query)
    compact_combined = search_normalized(f"{system} {name}")
    return bool(compact_query and compact_query in compact_combined)


ESRI_WORLD_IMAGERY = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)


def render_satellite_point_map(
    latitude: float,
    longitude: float,
    label: str,
    height: int = 500,
    zoom: int = 18,
) -> None:
    safe_label = html.escape(str(label or "Punto de medición"))

    fmap = folium.Map(
        location=[float(latitude), float(longitude)],
        zoom_start=zoom,
        tiles=None,
        control_scale=True,
        prefer_canvas=True,
    )

    folium.TileLayer(
        tiles=ESRI_WORLD_IMAGERY,
        attr="Esri, Maxar, Earthstar Geographics, and the GIS User Community",
        name="Esri World Imagery",
        overlay=False,
        control=False,
        max_zoom=20,
    ).add_to(fmap)

    folium.CircleMarker(
        location=[float(latitude), float(longitude)],
        radius=7,
        color="#FFFFFF",
        weight=3,
        fill=True,
        fill_color="#007AFF",
        fill_opacity=1.0,
        tooltip=folium.Tooltip(
            safe_label,
            permanent=True,
            sticky=False,
            direction="top",
            offset=(0, -5),
            style=(
                "background-color: rgba(20,28,38,0.92);"
                "color: #ffffff;"
                "font-size: 12px;"
                "font-weight: 700;"
                "line-height: 1.15;"
                "padding: 4px 8px;"
                "border: 1px solid rgba(255,255,255,0.92);"
                "border-radius: 6px;"
                "box-shadow: 0 2px 6px rgba(0,0,0,0.35);"
                "white-space: nowrap;"
            ),
        ),
    ).add_to(fmap)

    st_folium(
        fmap,
        width=None,
        height=height,
        use_container_width=True,
        returned_objects=[],
        key=f"sat-map-{float(latitude):.6f}-{float(longitude):.6f}-{safe_label}",
    )


def render_meter_map(row: pd.Series, height: int = 500) -> None:
    lat = row.get("LATITUD")
    lon = row.get("LONGITUD")
    if pd.isna(lat) or pd.isna(lon):
        st.warning("El punto seleccionado no tiene coordenadas WGS84 utilizables.")
        return

    label = meter_name(row) or "Caudalímetro"
    render_satellite_point_map(
        latitude=float(lat),
        longitude=float(lon),
        label=label,
        height=height,
        zoom=18,
    )
    st.caption(
        f"{label} · WGS84: {float(lat):.6f}, {float(lon):.6f} · "
        "Fondo satelital: Esri World Imagery"
    )


def render_measurement_point_map(
    latitude: float,
    longitude: float,
    label: str = "Punto de medición",
) -> None:
    render_satellite_point_map(
        latitude=float(latitude),
        longitude=float(longitude),
        label=label,
        height=320,
        zoom=18,
    )
    st.caption(
        f"{label} · WGS84: {float(latitude):.6f}, {float(longitude):.6f} · "
        "Fondo satelital: Esri World Imagery"
    )


def get_review_repo() -> SupabaseReviewRepository | None:
    if not settings.supabase_configured:
        return None
    return get_supabase_repo(settings)


def _review_date_value(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _quality_index(value: Any) -> int:
    try:
        return list(QUALITY_VALUES).index(str(value))
    except ValueError:
        return 1


def _rectification_index(value: Any) -> int:
    try:
        return list(RECTIFICATION_VALUES).index(str(value))
    except ValueError:
        return 0


def _yes_no_choice(value: Any) -> str:
    if value is True:
        return "Sí"
    if value is False:
        return "No"
    return "Sin verificar"


def _yes_no_value(choice: str) -> bool | None:
    if choice == "Sí":
        return True
    if choice == "No":
        return False
    return None


def _yes_no_index(value: Any) -> int:
    return ["Sin verificar", "Sí", "No"].index(_yes_no_choice(value))


def _maintenance_badge(
    value: Any,
    months: int,
    *,
    applicable: bool = True,
    condition_ok: bool = True,
) -> None:
    kind, message = maintenance_due_status(
        value,
        months,
        applicable=applicable,
        condition_ok=condition_ok,
    )
    status_badge(message, kind)


def render_maintenance_section(
    prefix: str,
    current: dict[str, Any] | None = None,
    equipment_type: str = "No definido",
) -> dict[str, Any]:
    current = current or {}
    st.markdown("### ASPECTOS DE MANTENIMIENTO")
    st.caption(
        "El semáforo se calcula automáticamente con la fecha registrada. "
        "Verde = vigente; rojo = vencido, sin fecha o condición no satisfactoria."
    )

    gel_applicable = st.checkbox(
        "Aplica cambio de gel",
        value=bool(
            current.get("maintenance_gel_applicable")
            if current.get("maintenance_gel_applicable") is not None
            else True
        ),
        key=f"{prefix}-maintenance-gel-applicable",
    )
    c1, c2 = st.columns([0.72, 0.28])
    gel_date = c1.date_input(
        "Cambio de gel",
        value=_review_date_value(current.get("maintenance_gel_date")),
        max_value=date.today(),
        disabled=not gel_applicable,
        key=f"{prefix}-maintenance-gel",
    )
    with c2:
        st.caption("Vigencia: 6 meses")
        _maintenance_badge(gel_date, 6, applicable=gel_applicable)

    alignment_applicable = st.checkbox(
        "Aplica alineación y sujeción de transductores",
        value=bool(
            current.get("maintenance_transducers_alignment_applicable")
            if current.get("maintenance_transducers_alignment_applicable") is not None
            else True
        ),
        key=f"{prefix}-maintenance-alignment-applicable",
    )
    c1, c2 = st.columns([0.72, 0.28])
    alignment_date = c1.date_input(
        "Transductores alineados y con buena sujeción",
        value=_review_date_value(
            current.get("maintenance_transducers_alignment_date")
        ),
        max_value=date.today(),
        disabled=not alignment_applicable,
        key=f"{prefix}-maintenance-alignment",
    )
    with c2:
        st.caption("Vigencia: 6 meses")
        _maintenance_badge(
            alignment_date,
            6,
            applicable=alignment_applicable,
        )

    download_applicable = st.checkbox(
        "Aplica descarga de datos internos del equipo",
        value=bool(
            current.get("maintenance_internal_download_applicable")
            if current.get("maintenance_internal_download_applicable") is not None
            else True
        ),
        key=f"{prefix}-maintenance-download-applicable",
        help="Desmarque para equipos antiguos donde esta función no aplica.",
    )
    c1, c2 = st.columns([0.72, 0.28])
    internal_download_date = c1.date_input(
        "Última descarga de datos internos",
        value=_review_date_value(
            current.get("maintenance_internal_download_date")
        ),
        max_value=date.today(),
        disabled=not download_applicable,
        key=f"{prefix}-maintenance-download",
    )
    with c2:
        st.caption("Vigencia: 6 meses")
        _maintenance_badge(
            internal_download_date,
            6,
            applicable=download_applicable,
        )

    c1, c2 = st.columns([0.72, 0.28])
    simultaneous_date = c1.date_input(
        "Última instalación simultánea con otro equipo",
        value=_review_date_value(
            current.get("maintenance_simultaneous_installation_date")
        ),
        max_value=date.today(),
        key=f"{prefix}-maintenance-simultaneous",
    )
    with c2:
        st.caption("Vigencia: 12 meses")
        _maintenance_badge(simultaneous_date, 12)

    insertion_cleaning_date = None
    if equipment_type == "Inserción":
        c1, c2 = st.columns([0.72, 0.28])
        insertion_cleaning_date = c1.date_input(
            "Limpieza del sensor de inserción",
            value=_review_date_value(
                current.get("maintenance_insertion_sensor_cleaning_date")
            ),
            max_value=date.today(),
            key=f"{prefix}-maintenance-insertion-cleaning",
        )
        with c2:
            st.caption("Vigencia: 12 meses")
            _maintenance_badge(insertion_cleaning_date, 12)

    solar_applicable = st.checkbox(
        "Aplica limpieza de panel solar y gabinete",
        value=bool(
            current.get("maintenance_solar_panel_applicable")
            if current.get("maintenance_solar_panel_applicable") is not None
            else False
        ),
        key=f"{prefix}-maintenance-solar-applicable",
    )
    c1, c2 = st.columns([0.72, 0.28])
    solar_cleaning_date = c1.date_input(
        "Limpieza de panel solar y gabinete",
        value=_review_date_value(
            current.get("maintenance_solar_panel_cleaning_date")
        ),
        max_value=date.today(),
        disabled=not solar_applicable,
        key=f"{prefix}-maintenance-solar-cleaning",
    )
    with c2:
        st.caption("Vigencia: 12 meses")
        _maintenance_badge(
            solar_cleaning_date,
            12,
            applicable=solar_applicable,
        )

    st.markdown("**Funcionamiento en SCADA**")
    s1, s2, s3 = st.columns([0.34, 0.38, 0.28])
    scada_choice = s1.selectbox(
        "¿Funciona en SCADA?",
        options=["Sin verificar", "Sí", "No"],
        index=_yes_no_index(current.get("maintenance_scada_working")),
        key=f"{prefix}-maintenance-scada-working",
    )
    scada_date = s2.date_input(
        "Fecha de verificación SCADA",
        value=_review_date_value(current.get("maintenance_scada_check_date")),
        max_value=date.today(),
        key=f"{prefix}-maintenance-scada-date",
    )
    with s3:
        st.caption("Vigencia: 1 mes")
        _maintenance_badge(
            scada_date,
            1,
            condition_ok=(scada_choice == "Sí"),
        )

    return {
        "maintenance_gel_applicable": bool(gel_applicable),
        "maintenance_gel_date": (
            gel_date.isoformat() if gel_applicable and gel_date else None
        ),
        "maintenance_transducers_alignment_applicable": bool(
            alignment_applicable
        ),
        "maintenance_transducers_alignment_date": (
            alignment_date.isoformat()
            if alignment_applicable and alignment_date
            else None
        ),
        "maintenance_internal_download_applicable": bool(download_applicable),
        "maintenance_internal_download_date": (
            internal_download_date.isoformat()
            if download_applicable and internal_download_date
            else None
        ),
        "maintenance_simultaneous_installation_date": (
            simultaneous_date.isoformat() if simultaneous_date else None
        ),
        "maintenance_insertion_sensor_cleaning_date": (
            insertion_cleaning_date.isoformat()
            if equipment_type == "Inserción" and insertion_cleaning_date
            else None
        ),
        "maintenance_solar_panel_applicable": bool(solar_applicable),
        "maintenance_solar_panel_cleaning_date": (
            solar_cleaning_date.isoformat()
            if solar_applicable and solar_cleaning_date
            else None
        ),
        "maintenance_scada_working": _yes_no_value(scada_choice),
        "maintenance_scada_check_date": (
            scada_date.isoformat() if scada_date else None
        ),
    }


def render_repairs_section(
    prefix: str,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = current or {}
    st.markdown("### ASPECTOS DE REPARACIÓN O MANTENIMIENTO")
    st.caption(
        "Por defecto cada aspecto está en verde. Marque únicamente cuando exista "
        "una falla, reparación o sustitución pendiente."
    )

    fields = [
        ("repair_signal_pending", "Señal"),
        ("repair_calibration_pending", "Calibración"),
        ("repair_power_pending", "Energía"),
        ("repair_wiring_pending", "Cableado"),
        ("repair_software_firmware_pending", "Actualización de Software / Firmware"),
        ("repair_perspective_pending", "Visualización en Perspective"),
        ("repair_vision_cco_pending", "Visualización en Vision Client de CCO (PC)"),
        (
            "repair_vision_scada_vr2_pending",
            "Visualización en Vision Client de SCADA vr2 (PC)",
        ),
        (
            "repair_vision_reports_pending",
            "Descarga de datos en módulo de reportes de Vision Client",
        ),
        ("repair_temporary_replacement", "Sustitución total temporal del equipo"),
        ("repair_permanent_replacement", "Sustitución total permanente del equipo"),
    ]

    payload: dict[str, Any] = {}
    for key, label in fields:
        r1, r2 = st.columns([0.72, 0.28])
        pending = r1.checkbox(
            f"{label}: existe pendiente / falla",
            value=bool(current.get(key, False)),
            key=f"{prefix}-{key}",
        )
        with r2:
            status_badge(
                "🔴 Pendiente" if pending else "🟢 Sin pendiente",
                "error" if pending else "success",
            )
        payload[key] = bool(pending)

    p1, p2 = st.columns([0.72, 0.28])
    spare_required = p1.checkbox(
        "Requiere un repuesto particular",
        value=bool(current.get("repair_spare_part_required", False)),
        key=f"{prefix}-repair-spare-part",
    )
    with p2:
        status_badge(
            "🔴 Requiere repuesto" if spare_required else "🟢 Sin pendiente",
            "error" if spare_required else "success",
        )
    spare_detail = ""
    if spare_required:
        spare_detail = st.text_input(
            "Indique cuál repuesto requiere",
            value=str(current.get("repair_spare_part_detail") or ""),
            key=f"{prefix}-repair-spare-detail",
        )

    payload["repair_spare_part_required"] = bool(spare_required)
    payload["repair_spare_part_detail"] = spare_detail.strip() or None
    return payload


def render_control_general_equipment(
    prefix: str,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = current or {}

    current_type = str(current.get("equipment_type") or "No definido")
    if current_type == "No definido" and current.get("is_ultrasonic"):
        current_type = "Ultrasónico"

    choices = [
        "Seleccione tipo de equipo",
        "Ultrasónico",
        "Electromagnético",
        "Inserción",
        "Canal Abierto",
    ]
    current_choice = (
        current_type if current_type in choices[1:] else choices[0]
    )
    equipment_type_choice = st.selectbox(
        "Tipo de equipo",
        options=choices,
        index=choices.index(current_choice),
        key=f"{prefix}-control-equipment-type",
    )
    equipment_type = (
        "No definido"
        if equipment_type_choice == "Seleccione tipo de equipo"
        else equipment_type_choice
    )

    equipment_serial = st.text_input(
        "Número de serie del equipo",
        value=str(current.get("equipment_serial") or ""),
        key=f"{prefix}-equipment-serial",
    )

    transducer_serial = None
    if equipment_type == "Ultrasónico":
        transducer_serial = (
            st.text_input(
                "Número de serie de transductores",
                value=str(current.get("transducer_serial") or ""),
                key=f"{prefix}-transducer-serial-control",
            ).strip()
            or None
        )
    else:
        st.caption(
            "Número de serie de transductores: no aplica para el tipo de equipo seleccionado."
        )

    return {
        "equipment_type": equipment_type,
        "equipment_serial": equipment_serial.strip() or None,
        "transducer_serial": transducer_serial,
    }


def render_equipment_generalities(
    prefix: str,
    equipment_type: str,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = current or {}
    st.markdown("### GENERALIDADES DEL EQUIPO")

    payload: dict[str, Any] = {
        "is_ultrasonic": equipment_type == "Ultrasónico",
        "pipe_material": None,
        "circumference_mm": None,
        "wall_thickness_mm": None,
        "transducer_distance_mm": None,
        "electromagnetic_diameter": None,
        "calibration_factor": None,
        "open_channel_height": None,
        "open_channel_width": None,
        "open_channel_x_downstream": None,
        "open_channel_y_downstream": None,
        "open_channel_surface_type": None,
        "insertion_depth": None,
        "insertion_diameter": None,
    }

    if equipment_type == "Ultrasónico":
        u1, u2, u3 = st.columns(3)
        circumference = u1.number_input(
            "Circunferencia [mm]",
            min_value=0.0,
            value=float(current.get("circumference_mm") or 0),
            step=0.1,
            format="%.2f",
            key=f"{prefix}-circumference",
        )
        thickness = u2.number_input(
            "Espesor [mm]",
            min_value=0.0,
            value=float(current.get("wall_thickness_mm") or 0),
            step=0.1,
            format="%.2f",
            key=f"{prefix}-wall-thickness",
        )
        distance = u3.number_input(
            "Distancia de transductores [mm]",
            min_value=0.0,
            value=float(current.get("transducer_distance_mm") or 0),
            step=0.1,
            format="%.2f",
            key=f"{prefix}-transducer-distance",
        )
        payload["circumference_mm"] = circumference
        payload["wall_thickness_mm"] = thickness
        payload["transducer_distance_mm"] = distance
        payload["pipe_material"] = (
            st.text_input(
                "Material de tubería",
                value=str(current.get("pipe_material") or ""),
                key=f"{prefix}-pipe-material",
            ).strip()
            or None
        )

    elif equipment_type == "Electromagnético":
        e1, e2 = st.columns(2)
        diameter = e1.number_input(
            "Diámetro",
            min_value=0.0,
            value=float(current.get("electromagnetic_diameter") or 0),
            step=0.1,
            key=f"{prefix}-electromagnetic-diameter",
        )
        calibration = e2.number_input(
            "Factor de calibración",
            min_value=0.0,
            value=float(current.get("calibration_factor") or 0),
            step=0.0001,
            format="%.4f",
            key=f"{prefix}-calibration-factor",
        )
        payload["electromagnetic_diameter"] = diameter or None
        payload["calibration_factor"] = calibration or None

    elif equipment_type == "Canal Abierto":
        c1, c2 = st.columns(2)
        payload["open_channel_height"] = c1.number_input(
            "Altura de canal",
            min_value=0.0,
            value=float(current.get("open_channel_height") or 0),
            step=0.01,
            key=f"{prefix}-channel-height",
        )
        payload["open_channel_width"] = c2.number_input(
            "Ancho de canal",
            min_value=0.0,
            value=float(current.get("open_channel_width") or 0),
            step=0.01,
            key=f"{prefix}-channel-width",
        )
        c3, c4 = st.columns(2)
        payload["open_channel_x_downstream"] = c3.number_input(
            "X del equipo en sentido aguas abajo",
            value=float(current.get("open_channel_x_downstream") or 0),
            step=0.01,
            key=f"{prefix}-channel-x",
        )
        payload["open_channel_y_downstream"] = c4.number_input(
            "Y del equipo en sentido aguas abajo",
            value=float(current.get("open_channel_y_downstream") or 0),
            step=0.01,
            key=f"{prefix}-channel-y",
        )
        payload["open_channel_surface_type"] = (
            st.text_input(
                "Tipo de superficie",
                value=str(current.get("open_channel_surface_type") or ""),
                key=f"{prefix}-channel-surface",
            ).strip()
            or None
        )

    elif equipment_type == "Inserción":
        i1, i2 = st.columns(2)
        depth = i1.number_input(
            "Profundidad de inserción",
            min_value=0.0,
            value=float(current.get("insertion_depth") or 0),
            step=0.1,
            key=f"{prefix}-insertion-depth",
        )
        diameter = i2.number_input(
            "Diámetro",
            min_value=0.0,
            value=float(current.get("insertion_diameter") or 0),
            step=0.1,
            key=f"{prefix}-insertion-diameter",
        )
        payload["insertion_depth"] = depth or None
        payload["insertion_diameter"] = diameter or None

    elif equipment_type == "No definido":
        st.info("Seleccione el tipo de equipo en Control general de la revisión.")

    return payload


def render_review_maintenance_status(review: dict[str, Any]) -> None:
    st.markdown("### Estado de mantenimiento")
    equipment_type = str(review.get("equipment_type") or "No definido")
    maintenance_rows = [
        (
            "Cambio de gel",
            "maintenance_gel_date",
            6,
            bool(review.get("maintenance_gel_applicable", True)),
            True,
        ),
        (
            "Alineación y sujeción de transductores",
            "maintenance_transducers_alignment_date",
            6,
            bool(
                review.get("maintenance_transducers_alignment_applicable", True)
            ),
            True,
        ),
        (
            "Descarga de datos internos",
            "maintenance_internal_download_date",
            6,
            bool(review.get("maintenance_internal_download_applicable", True)),
            True,
        ),
        (
            "Instalación simultánea con otro equipo",
            "maintenance_simultaneous_installation_date",
            12,
            True,
            True,
        ),
        (
            "Limpieza del sensor de inserción",
            "maintenance_insertion_sensor_cleaning_date",
            12,
            equipment_type == "Inserción",
            True,
        ),
        (
            "Limpieza de panel solar y gabinete",
            "maintenance_solar_panel_cleaning_date",
            12,
            bool(review.get("maintenance_solar_panel_applicable", False)),
            True,
        ),
        (
            "Funcionamiento en SCADA",
            "maintenance_scada_check_date",
            1,
            True,
            review.get("maintenance_scada_working") is True,
        ),
    ]
    for label, key, months, applies, condition_ok in maintenance_rows:
        m1, m2 = st.columns([0.62, 0.38])
        value = review.get(key)
        m1.write(f"**{label}:** {value or 'Sin fecha'}")
        with m2:
            _maintenance_badge(
                value,
                months,
                applicable=applies,
                condition_ok=condition_ok,
            )


def render_review_repairs_status(review: dict[str, Any]) -> None:
    st.markdown("### Aspectos de reparación o mantenimiento")
    repair_rows = [
        ("Señal", "repair_signal_pending"),
        ("Calibración", "repair_calibration_pending"),
        ("Energía", "repair_power_pending"),
        ("Cableado", "repair_wiring_pending"),
        ("Actualización de Software / Firmware", "repair_software_firmware_pending"),
        ("Visualización en Perspective", "repair_perspective_pending"),
        ("Vision Client CCO", "repair_vision_cco_pending"),
        ("Vision Client SCADA vr2", "repair_vision_scada_vr2_pending"),
        ("Descarga módulo de reportes", "repair_vision_reports_pending"),
        ("Sustitución temporal", "repair_temporary_replacement"),
        ("Sustitución permanente", "repair_permanent_replacement"),
    ]
    for label, key in repair_rows:
        pending = bool(review.get(key, False))
        r1, r2 = st.columns([0.72, 0.28])
        r1.write(label)
        with r2:
            status_badge(
                "🔴 Pendiente" if pending else "🟢 Sin pendiente",
                "error" if pending else "success",
            )

    spare = bool(review.get("repair_spare_part_required", False))
    r1, r2 = st.columns([0.72, 0.28])
    detail = str(review.get("repair_spare_part_detail") or "").strip()
    r1.write("Repuesto particular" + (f": {detail}" if spare and detail else ""))
    with r2:
        status_badge(
            "🔴 Requiere repuesto" if spare else "🟢 Sin pendiente",
            "error" if spare else "success",
        )


def render_review_generalities(review: dict[str, Any]) -> None:
    st.markdown("### Generalidades del equipo")
    equipment_type = str(review.get("equipment_type") or "No definido")
    general_rows = [
        ("Tipo de equipo", equipment_type),
        ("Número de serie del equipo", review.get("equipment_serial")),
    ]
    if equipment_type == "Ultrasónico" or review.get("is_ultrasonic"):
        general_rows.extend(
            [
                ("Número de serie de transductores", review.get("transducer_serial")),
                ("Circunferencia [mm]", review.get("circumference_mm")),
                ("Espesor [mm]", review.get("wall_thickness_mm")),
                (
                    "Distancia de transductores [mm]",
                    review.get("transducer_distance_mm"),
                ),
                ("Material de tubería", review.get("pipe_material")),
            ]
        )
    elif equipment_type == "Electromagnético":
        general_rows.extend(
            [
                ("Diámetro", review.get("electromagnetic_diameter")),
                ("Factor de calibración", review.get("calibration_factor")),
            ]
        )
    elif equipment_type == "Canal Abierto":
        general_rows.extend(
            [
                ("Altura de canal", review.get("open_channel_height")),
                ("Ancho de canal", review.get("open_channel_width")),
                ("X aguas abajo", review.get("open_channel_x_downstream")),
                ("Y aguas abajo", review.get("open_channel_y_downstream")),
                ("Tipo de superficie", review.get("open_channel_surface_type")),
            ]
        )
    elif equipment_type == "Inserción":
        general_rows.extend(
            [
                ("Profundidad de inserción", review.get("insertion_depth")),
                ("Diámetro", review.get("insertion_diameter")),
            ]
        )

    st.dataframe(
        pd.DataFrame(general_rows, columns=["Campo", "Valor"]),
        hide_index=True,
        width="stretch",
    )


def render_review_control_sections(review: dict[str, Any]) -> None:
    render_review_maintenance_status(review)
    render_review_repairs_status(review)
    render_review_generalities(review)


@st.dialog("Editar revisión")
def edit_review_dialog(
    review: dict[str, Any],
    review_repo: SupabaseReviewRepository,
) -> None:
    review_id = str(review.get("id") or "")
    old_storage_path = str(review.get("graph_storage_path") or "").strip() or None
    old_graph_source = str(review.get("graph_source") or "none")
    old_graph_format = str(review.get("graph_format") or "html")
    old_sharepoint_url = str(review.get("graph_original_url") or "").strip()

    st.caption(
        "Los atributos históricos de la geodatabase se mantienen sin cambios. "
        "Aquí puede corregir la información registrada en la revisión."
    )

    st.markdown("### CONTROL GENERAL DE LA REVISIÓN")
    control_fields = render_control_general_equipment(
        f"edit-{review_id}",
        review,
    )

    rectification_status = st.radio(
        "Rectificación",
        options=list(RECTIFICATION_VALUES),
        index=_rectification_index(review.get("rectification_status")),
        key=f"edit-rectification-{review_id}",
    )
    rectification_equipment = ""
    if rectification_status == "Sí, con medición simultánea":
        rectification_equipment = st.text_input(
            "Equipo utilizado para rectificar",
            value=str(review.get("rectification_equipment") or ""),
            key=f"edit-rectification-equipment-{review_id}",
        )

    measurement_quality = st.selectbox(
        "Calidad de medición",
        options=list(QUALITY_VALUES),
        index=_quality_index(review.get("measurement_quality")),
        key=f"edit-quality-{review_id}",
    )

    last_maintenance_date = st.date_input(
        "Fecha del último mantenimiento / revisión",
        value=_review_date_value(review.get("last_maintenance_date")),
        max_value=date.today(),
        key=f"edit-maintenance-{review_id}",
    )
    reviewed_by = st.text_input(
        "Revisado por",
        value=str(review.get("reviewed_by") or ""),
        key=f"edit-reviewed-by-{review_id}",
    )
    notes = st.text_area(
        "Observaciones adicionales",
        value=str(review.get("notes") or ""),
        height=90,
        key=f"edit-notes-{review_id}",
    )

    maintenance_fields = render_maintenance_section(
        f"edit-{review_id}",
        review,
        equipment_type=control_fields["equipment_type"],
    )
    repair_fields = render_repairs_section(
        f"edit-{review_id}",
        review,
    )
    equipment_fields = render_equipment_generalities(
        f"edit-{review_id}",
        control_fields["equipment_type"],
        review,
    )

    st.markdown("#### Punto de medición")
    has_measurement_point = (
        review.get("measurement_latitude") is not None
        and review.get("measurement_longitude") is not None
    )
    register_measurement_point = st.checkbox(
        "Registrar punto de medición puntual",
        value=has_measurement_point,
        key=f"edit-point-enabled-{review_id}",
    )
    measurement_latitude_text = ""
    measurement_longitude_text = ""
    measurement_location_notes = ""
    if register_measurement_point:
        m1, m2 = st.columns(2)
        measurement_latitude_text = m1.text_input(
            "Latitud WGS84",
            value=(
                "" if review.get("measurement_latitude") is None
                else str(review.get("measurement_latitude"))
            ),
            key=f"edit-lat-{review_id}",
        )
        measurement_longitude_text = m2.text_input(
            "Longitud WGS84",
            value=(
                "" if review.get("measurement_longitude") is None
                else str(review.get("measurement_longitude"))
            ),
            key=f"edit-lon-{review_id}",
        )
        measurement_location_notes = st.text_input(
            "Referencia del punto",
            value=str(review.get("measurement_location_notes") or ""),
            key=f"edit-point-notes-{review_id}",
        )

    st.markdown("#### Gráfico")
    graph_labels = {
        "none": "Sin gráfico",
        "manual": "Archivo HTML",
        "sharepoint_link": "Vínculo MS List / SharePoint",
        "sharepoint": "Vínculo MS List / SharePoint",
    }
    graph_values = ["none", "manual", "sharepoint_link"]
    normalized_source = (
        "sharepoint_link" if old_graph_source == "sharepoint" else old_graph_source
    )
    if normalized_source not in graph_values:
        normalized_source = "none"
    selected_graph_source = st.selectbox(
        "Origen del gráfico",
        options=graph_values,
        index=graph_values.index(normalized_source),
        format_func=lambda value: graph_labels[value],
        key=f"edit-graph-source-{review_id}",
    )

    sharepoint_url = ""
    replacement_html = None
    if selected_graph_source == "sharepoint_link":
        sharepoint_url = st.text_input(
            "Hipervínculo SharePoint",
            value=old_sharepoint_url,
            key=f"edit-sharepoint-url-{review_id}",
        )
        if sharepoint_url.strip():
            parsed_link = parse_sharepoint_attachment_url(sharepoint_url)
            if parsed_link and parsed_link.get("item_id"):
                st.caption(
                    f"ID detectado: {parsed_link['item_id']} · "
                    f"{parsed_link.get('file_name') or 'archivo no identificado'}"
                )
    elif selected_graph_source == "manual":
        replacement_html = st.file_uploader(
            "Reemplazar HTML (opcional)",
            type=["html", "htm"],
            key=f"edit-html-{review_id}",
            help=(
                "Si ya existe un HTML manual y no selecciona otro archivo, "
                "se conserva el actual."
            ),
        )

    if st.button(
        "Guardar cambios",
        type="primary",
        use_container_width=True,
        key=f"save-edit-review-{review_id}",
    ):
        validation_data = {
            "rectification_status": rectification_status,
            "rectification_equipment": rectification_equipment,
            "is_ultrasonic": equipment_fields["is_ultrasonic"],
            "circumference_mm": equipment_fields["circumference_mm"],
            "wall_thickness_mm": equipment_fields["wall_thickness_mm"],
            "transducer_distance_mm": equipment_fields["transducer_distance_mm"],
            "measurement_quality": measurement_quality,
        }
        errors = list(validate_review(validation_data).errors)
        if control_fields.get("equipment_type") == "No definido":
            errors.append("Seleccione el tipo de equipo.")
        if (
            repair_fields.get("repair_spare_part_required")
            and not repair_fields.get("repair_spare_part_detail")
        ):
            errors.append("Indique cuál repuesto particular requiere el equipo.")

        measurement_latitude = None
        measurement_longitude = None
        if register_measurement_point:
            (
                measurement_latitude,
                measurement_longitude,
                coordinate_validation,
            ) = parse_measurement_coordinates(
                measurement_latitude_text,
                measurement_longitude_text,
            )
            errors.extend(coordinate_validation.errors)

        new_storage_path = old_storage_path
        graph_format = old_graph_format
        graph_original_url = None
        sharepoint_item_id = None
        sharepoint_file_name = None
        storage_path_to_cleanup = None

        if selected_graph_source == "none":
            if old_storage_path:
                storage_path_to_cleanup = old_storage_path
            new_storage_path = None
            graph_format = "html"

        elif selected_graph_source == "sharepoint_link":
            parsed_link = parse_sharepoint_attachment_url(sharepoint_url)
            if not sharepoint_url.strip():
                errors.append("Ingrese el vínculo SharePoint del gráfico.")
            elif parsed_link is None:
                errors.append(
                    "El vínculo debe ser HTTPS y pertenecer a un dominio *.sharepoint.com."
                )
            else:
                graph_original_url = sharepoint_url.strip()
                sharepoint_item_id = parsed_link.get("item_id")
                sharepoint_file_name = parsed_link.get("file_name")
                if (
                    old_graph_source not in {"sharepoint", "sharepoint_link"}
                    or graph_original_url != old_sharepoint_url
                ):
                    if old_storage_path:
                        storage_path_to_cleanup = old_storage_path
                    new_storage_path = None
                    graph_format = "html"

        elif selected_graph_source == "manual":
            if replacement_html is not None:
                html_validation = validate_html_file(
                    replacement_html.name,
                    replacement_html.getvalue(),
                )
                errors.extend(html_validation.errors)
            elif old_graph_source != "manual" or not old_storage_path:
                errors.append(
                    "Seleccione un archivo HTML para cambiar el origen del gráfico a manual."
                )

        if errors:
            for error in errors:
                st.error(error)
            return

        try:
            if selected_graph_source == "manual" and replacement_html is not None:
                uploaded_path = review_repo.upload_html(
                    equipment_key=str(review.get("equipment_key") or ""),
                    filename=replacement_html.name,
                    content=replacement_html.getvalue(),
                )
                if old_storage_path and old_storage_path != uploaded_path:
                    storage_path_to_cleanup = old_storage_path
                new_storage_path = uploaded_path
                graph_format = "html"
                sharepoint_file_name = replacement_html.name

            payload = {
                "rectification_status": rectification_status,
                "rectification_equipment": rectification_equipment.strip() or None,
                "measurement_quality": measurement_quality,
                "last_maintenance_date": (
                    last_maintenance_date.isoformat()
                    if last_maintenance_date
                    else None
                ),
                "notes": notes.strip() or None,
                "reviewed_by": reviewed_by.strip() or None,
                "measurement_latitude": (
                    measurement_latitude if register_measurement_point else None
                ),
                "measurement_longitude": (
                    measurement_longitude if register_measurement_point else None
                ),
                "measurement_location_notes": (
                    measurement_location_notes.strip() or None
                    if register_measurement_point
                    else None
                ),
                "graph_source": selected_graph_source,
                "graph_format": graph_format,
                "graph_storage_path": new_storage_path,
                "graph_original_url": graph_original_url,
                "sharepoint_item_id": sharepoint_item_id,
                "sharepoint_file_name": sharepoint_file_name,
            }
            payload.update(control_fields)
            payload.update(equipment_fields)
            payload.update(maintenance_fields)
            payload.update(repair_fields)

            review_repo.update_review(review_id, payload)

            if storage_path_to_cleanup and storage_path_to_cleanup != new_storage_path:
                try:
                    review_repo.delete_html(storage_path_to_cleanup)
                except Exception:
                    pass

            st.session_state["review_action_message"] = "Revisión actualizada correctamente."
            st.rerun()
        except Exception as exc:
            st.error(f"No fue posible actualizar la revisión: {exc}")


@st.dialog("Eliminar revisión")
def delete_review_dialog(
    review: dict[str, Any],
    review_repo: SupabaseReviewRepository,
) -> None:
    review_id = str(review.get("id") or "")
    st.warning(
        "Esta acción elimina definitivamente este registro del historial. "
        "No modifica la geodatabase del caudalímetro."
    )
    st.write(
        f"**Registro:** {review.get('reviewed_at') or 'Sin fecha'} · "
        f"{review.get('measurement_quality') or 'Sin calidad'}"
    )
    confirm = st.checkbox(
        "Confirmo que deseo eliminar esta revisión.",
        key=f"confirm-delete-review-{review_id}",
    )
    if st.button(
        "Eliminar definitivamente",
        type="primary",
        use_container_width=True,
        disabled=not confirm,
        key=f"delete-review-{review_id}",
    ):
        try:
            result = review_repo.delete_review(
                review_id=review_id,
                graph_storage_path=review.get("graph_storage_path"),
            )
            message = "Revisión eliminada correctamente."
            if result.get("storage_warning"):
                message += " " + str(result["storage_warning"])
            st.session_state["review_action_message"] = message
            st.rerun()
        except Exception as exc:
            st.error(f"No fue posible eliminar la revisión: {exc}")


@st.dialog("Gráfico comparativo de mediciones", width="large")
def large_graph_dialog(
    graph_content: bytes,
    graph_format: str,
    graph_key: str,
    equipment_label: str,
) -> None:
    if equipment_label:
        st.caption(equipment_label)
    render_stored_graph(
        graph_content,
        graph_format=graph_format,
        key=f"large-{graph_key}",
        height=780,
    )


def render_graph_for_review(
    review: dict[str, Any],
    review_repo: SupabaseReviewRepository | None,
) -> None:
    source = review.get("graph_source") or "none"

    if source == "manual":
        path = review.get("graph_storage_path")
        if not path:
            st.info("La revisión indica un gráfico manual, pero no existe ruta almacenada.")
            return
        if review_repo is None:
            st.warning("Supabase no está configurado; no es posible recuperar el gráfico.")
            return
        try:
            content = review_repo.download_html(str(path))
            graph_format = str(review.get("graph_format") or "html")
            graph_id = str(review.get("id") or path)
            if st.button(
                "⛶ Ver gráfico en pantalla grande",
                key=f"expand-manual-{graph_id}",
                use_container_width=True,
            ):
                large_graph_dialog(
                    content,
                    graph_format=graph_format,
                    graph_key=f"manual-{graph_id}",
                    equipment_label=str(
                        review.get("equipment_label") or "Caudalímetro"
                    ),
                )
            render_stored_graph(
                content,
                graph_format=graph_format,
                key=f"manual-{graph_id}",
            )
        except Exception as exc:
            st.error(f"No fue posible recuperar el HTML desde Supabase: {exc}")
        return

    if source == "sharepoint_link":
        original_url = str(review.get("graph_original_url") or "").strip()
        if original_url:
            st.link_button(
                "Abrir vínculo original en Microsoft List / SharePoint",
                original_url,
                use_container_width=True,
            )

        cached_path = review.get("graph_storage_path")
        if cached_path and review_repo is not None:
            try:
                content = review_repo.download_html(str(cached_path))
                graph_format = str(review.get("graph_format") or "html")
                if graph_format == "plotly_json_gzip":
                    st.success("Gráfico Plotly optimizado y sincronizado en Supabase.")
                else:
                    st.success("HTML de SharePoint sincronizado en Supabase.")
                graph_id = str(review.get("id") or cached_path)
                if st.button(
                    "⛶ Ver gráfico en pantalla grande",
                    key=f"expand-sharepoint-{graph_id}",
                    use_container_width=True,
                ):
                    large_graph_dialog(
                        content,
                        graph_format=graph_format,
                        graph_key=f"sharepoint-{graph_id}",
                        equipment_label=str(
                            review.get("equipment_label") or "Caudalímetro"
                        ),
                    )
                render_stored_graph(
                    content,
                    graph_format=graph_format,
                    key=f"sharepoint-local-{graph_id}",
                )
                return
            except Exception as exc:
                st.warning(f"No fue posible abrir la copia HTML almacenada: {exc}")

        st.info(
            "Pendiente de importación automática desde SharePoint. "
            "El gráfico aparecerá aquí cuando el agente de sincronización lo procese."
        )
        return

    if source == "sharepoint":
        st.info(
            "Esta revisión proviene de la integración SharePoint anterior. "
            "Registre el vínculo como 'Vínculo MS List / SharePoint' para usar "
            "la sincronización local por Microsoft Edge."
        )
        return

    st.info("Esta revisión no tiene gráfico comparativo asociado.")


try:
    with st.spinner("Cargando inventario de caudalímetros..."):
        meters = load_meters(settings)
except Exception as exc:
    st.error("No fue posible cargar el inventario de caudalímetros.")
    st.exception(exc)
    if settings.meter_data_source == "supabase":
        st.info(
            "Verifique que haya ejecutado supabase_schema.sql y que la tabla "
            f"public.{settings.supabase_meters_table} haya sido alimentada con "
            "sincronizar_caudalimetros.py desde una computadora dentro de la red AyA."
        )
    st.stop()

if meters.empty:
    if settings.meter_data_source == "supabase":
        st.warning(
            "Supabase todavía no contiene caudalímetros. Ejecute "
            "sincronizar_caudalimetros.py desde una computadora con acceso al SQL de AyA."
        )
    else:
        st.warning("La consulta SQL no devolvió caudalímetros con geometría.")
    st.stop()

key_column = determine_key_column_from_frame(meters, settings.sql_key_field)
meters = meters.reset_index(drop=True)

st.sidebar.title("Seguimiento de Caudalímetros")
if settings.demo_mode:
    st.sidebar.warning("Modo demostración activo.")
else:
    st.sidebar.info(
        f"Fuente de inventario: {settings.meter_data_source.upper()}"
    )

page = st.sidebar.radio(
    "Vista",
    ["Revisión de equipo", "Ficha e historial", "Diagnóstico"],
)

columns = [str(column) for column in meters.columns]
system_column = find_column(
    columns,
    [
        "OBSERVACIO",
        "OBSERVACION",
        "Observacio",
        "Observacion",
        "Sistema_De_Abastecimiento",
        "Sistema de Abastecimiento",
        "SISTEMA_DE_ABASTECIMIENTO",
        "Código_Sistema",
        "Codigo_Sistema",
        "CODIGO_SISTEMA",
        "Sistema",
        "SISTEMA",
        "NOMBRE_SISTEMA",
    ],
)
name_column = find_column(
    columns,
    [
        "DESCRIPCIO",
        "DESCRIPCION",
        "Descripcion",
        "Descripción",
        "Nombre_Caudalimetro",
        "Nombre del Caudalímetro",
        "NOMBRE_CAUDALIMETRO",
        "Nombre_Equipo",
        "NOMBRE_EQUIPO",
        "Nombre",
        "NOMBRE",
        "DESCRIPCION",
        "Descripción",
        "UBICACION",
    ],
)

st.sidebar.markdown("### Buscar equipo")
search_text = st.sidebar.text_input(
    "Sistema o nombre",
    placeholder="Ej.: MEA01, Planta Alta Salida",
)

filtered_meters = meters.copy()
if system_column:
    system_values = sorted(
        {
            str(value).strip()
            for value in meters[system_column].dropna().tolist()
            if str(value).strip()
        },
        key=lambda value: search_normalized(value),
    )
    selected_system = st.sidebar.selectbox(
        "Sistema de Abastecimiento",
        options=["Todos"] + system_values,
    )
    if selected_system != "Todos":
        filtered_meters = filtered_meters[
            filtered_meters[system_column].astype(str).str.strip() == selected_system
        ]
else:
    st.sidebar.caption(
        "No se identificó una columna específica de Sistema de Abastecimiento."
    )

if search_text.strip():
    mask = filtered_meters.apply(
        lambda row: meter_matches_search(
            row,
            search_text,
            system_column,
            name_column,
        ),
        axis=1,
    )
    filtered_meters = filtered_meters[mask]

if filtered_meters.empty:
    st.sidebar.warning("No se encontraron caudalímetros con ese sistema o nombre.")
    st.stop()

candidate_indices = sorted(
    filtered_meters.index.tolist(),
    key=lambda idx: search_normalized(
        meter_label(
            meters.loc[idx],
            key_column,
            system_column,
            name_column,
        )
    ),
)

selected_index = st.sidebar.selectbox(
    "Caudalímetro / nombre",
    options=candidate_indices,
    format_func=lambda idx: meter_label(
        meters.loc[idx],
        key_column,
        system_column,
        name_column,
    ),
)
selected_row = meters.loc[selected_index]
equipment_key = str(selected_row.get(key_column))
selected_system_name = meter_system(selected_row, system_column)
selected_meter_name = meter_name(selected_row, name_column)
snapshot = snapshot_from_row(selected_row.to_dict())

st.sidebar.caption(f"Resultados: {len(filtered_meters)} equipo(s)")
if st.sidebar.button("Actualizar datos"):
    load_meters.clear()
    st.rerun()


st.title("Control de revisión de caudalímetros")
st.caption(
    "Los atributos del inventario provienen de la geodatabase y son únicamente de lectura. "
    "En Streamlit Cloud se consulta la copia operacional sincronizada en Supabase; "
    "las revisiones y su historial se almacenan separadamente."
)


if page == "Revisión de equipo":
    st.subheader("Revisión de equipo")

    # Referencia del activo: mapa y atributos siempre visibles en la parte superior.
    top_map, top_data = st.columns([0.48, 0.52], gap="large")
    with top_map:
        st.markdown("#### Ubicación del equipo")
        render_meter_map(selected_row, height=390)

    with top_data:
        st.markdown("#### Atributos de la geodatabase")
        readonly_snapshot(snapshot, title="Datos del inventario")

    st.markdown("---")
    st.subheader("Formulario de revisión")
    if selected_system_name:
        st.caption(f"Sistema de Abastecimiento: {selected_system_name}")
    st.caption(f"Equipo: {selected_meter_name or 'Sin nombre registrado'}")

    form_left, form_right = st.columns(2, gap="large")

    with form_left:
        st.markdown("### CONTROL GENERAL DE LA REVISIÓN")
        control_fields = render_control_general_equipment("new")

        rectification_status = st.radio(
            "¿El equipo se ha logrado rectificar con otro equipo de forma simultánea?",
            options=list(RECTIFICATION_VALUES),
            horizontal=True,
        )
        rectification_equipment = ""
        if rectification_status == "Sí, con medición simultánea":
            rectification_equipment = st.text_input(
                "¿Con cuál equipo se realizó la rectificación?",
                placeholder="Ej.: ultrasónico portátil / marca-modelo / código interno",
            )

        g1, g2 = st.columns(2)
        measurement_quality = g1.selectbox(
            "Calidad de medición",
            options=list(QUALITY_VALUES),
            index=1,
        )
        last_maintenance_date = g2.date_input(
            "Fecha del último mantenimiento / revisión",
            value=None,
            max_value=date.today(),
        )
        reviewed_by = st.text_input(
            "Revisado por",
            placeholder="Nombre o usuario responsable",
        )

        maintenance_fields = render_maintenance_section(
            "new",
            equipment_type=control_fields["equipment_type"],
        )

    with form_right:
        repair_fields = render_repairs_section("new")
        equipment_fields = render_equipment_generalities(
            "new",
            control_fields["equipment_type"],
        )

        st.markdown("### PUNTO DE MEDICIÓN PUNTUAL")
        register_measurement_point = st.checkbox(
            "Registrar un punto de medición distinto o complementario al macromedidor"
        )
        measurement_latitude_text = ""
        measurement_longitude_text = ""
        measurement_location_notes = ""
        if register_measurement_point:
            meter_lat = selected_row.get("LATITUD")
            meter_lon = selected_row.get("LONGITUD")
            if pd.notna(meter_lat) and pd.notna(meter_lon):
                st.caption(
                    f"Referencia del macromedidor: {float(meter_lat):.6f}, "
                    f"{float(meter_lon):.6f}. Ingrese abajo el punto real de la medición."
                )
            p1, p2 = st.columns(2)
            measurement_latitude_text = p1.text_input(
                "Latitud WGS84",
                placeholder="Ej.: 9.928100",
            )
            measurement_longitude_text = p2.text_input(
                "Longitud WGS84",
                placeholder="Ej.: -84.090700",
            )
            measurement_location_notes = st.text_input(
                "Referencia del punto de medición",
                placeholder="Ej.: válvula, hidrante, cámara o punto aguas abajo",
            )

        st.markdown("### GRÁFICO COMPARATIVO")
        graph_options = [
            "Sin gráfico",
            "Cargar archivo HTML",
            "Vínculo MS List / SharePoint",
        ]
        graph_option = st.radio(
            "Origen del gráfico",
            graph_options,
            horizontal=True,
        )

        uploaded_html = None
        sharepoint_url = ""
        sharepoint_item_id = None
        sharepoint_file_name = None

        if graph_option == "Cargar archivo HTML":
            uploaded_html = st.file_uploader(
                "Archivo HTML de comparación",
                type=["html", "htm"],
                help=(
                    "Se almacenará en un bucket privado de Supabase "
                    "y se mostrará dentro de la ficha."
                ),
            )
            if uploaded_html:
                validation = validate_html_file(
                    uploaded_html.name,
                    uploaded_html.getvalue(),
                )
                if validation.ok:
                    status_badge("HTML válido para carga", "success")
                else:
                    for error in validation.errors:
                        st.error(error)

        elif graph_option == "Vínculo MS List / SharePoint":
            sharepoint_url = st.text_input(
                "Hipervínculo del archivo HTML en Microsoft List / SharePoint",
                placeholder=(
                    "https://...sharepoint.com/.../Attachments/"
                    "2324/grafico.html?web=1"
                ),
            )
            parsed_link = parse_sharepoint_attachment_url(sharepoint_url)
            if sharepoint_url.strip():
                if parsed_link is None:
                    st.warning(
                        "El vínculo debe ser HTTPS y pertenecer a un dominio *.sharepoint.com."
                    )
                elif parsed_link.get("item_id"):
                    st.caption(
                        f"ID de Microsoft List detectado: {parsed_link['item_id']} · "
                        f"Archivo: {parsed_link.get('file_name') or 'no identificado'}"
                    )
                else:
                    st.caption(
                        "El vínculo se guardará, aunque no se pudo extraer "
                        "automáticamente el ID del elemento."
                    )

            st.info(
                "El vínculo se guardará y el agente de sincronización importará "
                "automáticamente el gráfico desde SharePoint hacia Supabase."
            )

        notes = st.text_area("Observaciones adicionales", height=90)

    st.markdown("---")
    save_disabled = not settings.supabase_configured
    if save_disabled:
        st.warning(
            "Supabase no está configurado. El formulario puede revisarse, "
            "pero no se habilita el guardado."
        )

    if st.button(
        "Guardar revisión",
        type="primary",
        use_container_width=True,
        disabled=save_disabled,
    ):
        data = {
            "rectification_status": rectification_status,
            "rectification_equipment": rectification_equipment,
            "is_ultrasonic": equipment_fields["is_ultrasonic"],
            "circumference_mm": equipment_fields["circumference_mm"],
            "wall_thickness_mm": equipment_fields["wall_thickness_mm"],
            "transducer_distance_mm": equipment_fields["transducer_distance_mm"],
            "measurement_quality": measurement_quality,
        }
        validation = validate_review(data)
        errors = list(validation.errors)
        if control_fields.get("equipment_type") == "No definido":
            errors.append("Seleccione el tipo de equipo.")
        if (
            repair_fields.get("repair_spare_part_required")
            and not repair_fields.get("repair_spare_part_detail")
        ):
            errors.append("Indique cuál repuesto particular requiere el equipo.")

        measurement_latitude = None
        measurement_longitude = None
        if register_measurement_point:
            (
                measurement_latitude,
                measurement_longitude,
                coordinate_validation,
            ) = parse_measurement_coordinates(
                measurement_latitude_text,
                measurement_longitude_text,
            )
            errors.extend(coordinate_validation.errors)

        graph_source = "none"
        graph_storage_path = None

        if graph_option == "Cargar archivo HTML":
            if uploaded_html is None:
                errors.append("Seleccione un archivo HTML para el gráfico comparativo.")
            else:
                html_validation = validate_html_file(
                    uploaded_html.name,
                    uploaded_html.getvalue(),
                )
                errors.extend(html_validation.errors)
                graph_source = "manual"

        elif graph_option == "Vínculo MS List / SharePoint":
            parsed_link = parse_sharepoint_attachment_url(sharepoint_url)
            if not sharepoint_url.strip():
                errors.append(
                    "Ingrese el hipervínculo del archivo HTML en Microsoft List."
                )
            elif parsed_link is None:
                errors.append(
                    "El hipervínculo debe ser HTTPS y pertenecer "
                    "a un dominio *.sharepoint.com."
                )
            else:
                graph_source = "sharepoint_link"
                sharepoint_item_id = parsed_link.get("item_id")
                sharepoint_file_name = parsed_link.get("file_name")

        if errors:
            for error in errors:
                st.error(error)
        else:
            review_repo = get_review_repo()
            if review_repo is None:
                st.error("Supabase no está configurado.")
            else:
                try:
                    if graph_source == "manual" and uploaded_html is not None:
                        graph_storage_path = review_repo.upload_html(
                            equipment_key=equipment_key,
                            filename=uploaded_html.name,
                            content=uploaded_html.getvalue(),
                        )

                    payload = {
                        "equipment_key": equipment_key,
                        "equipment_label": meter_label(
                            selected_row,
                            key_column,
                            system_column,
                            name_column,
                        ),
                        "sql_key_field": key_column,
                        "geodatabase_snapshot": snapshot,
                        "rectification_status": rectification_status,
                        "rectification_equipment": rectification_equipment or None,
                        "measurement_quality": measurement_quality,
                        "graph_source": graph_source,
                        "graph_format": "html",
                        "graph_storage_path": graph_storage_path,
                        "sharepoint_item_id": sharepoint_item_id,
                        "sharepoint_file_name": sharepoint_file_name,
                        "last_maintenance_date": (
                            last_maintenance_date.isoformat()
                            if last_maintenance_date
                            else None
                        ),
                        "notes": notes.strip() or None,
                        "reviewed_by": reviewed_by.strip() or None,
                    }
                    if graph_source == "sharepoint_link":
                        payload["graph_original_url"] = sharepoint_url.strip()
                    if register_measurement_point:
                        payload["measurement_latitude"] = measurement_latitude
                        payload["measurement_longitude"] = measurement_longitude
                        payload["measurement_location_notes"] = (
                            measurement_location_notes.strip() or None
                        )

                    payload.update(control_fields)
                    payload.update(equipment_fields)
                    payload.update(maintenance_fields)
                    payload.update(repair_fields)

                    saved = review_repo.insert_review(payload)
                    st.success(
                        "Revisión guardada correctamente. "
                        f"ID: {saved.get('id', 'registrado')}"
                    )
                    if graph_source == "sharepoint_link":
                        st.info(
                            "Vínculo SharePoint guardado. El agente lo importará "
                            "automáticamente a Supabase."
                        )
                except Exception as exc:
                    st.error(f"No fue posible guardar la revisión: {exc}")


elif page == "Ficha e historial":
    review_repo = get_review_repo()
    if review_repo is None:
        st.warning("Configure Supabase para consultar la ficha e historial.")
        st.stop()

    try:
        reviews = review_repo.list_reviews(equipment_key=equipment_key, limit=250)
    except Exception as exc:
        st.error(f"No fue posible consultar las revisiones en Supabase: {exc}")
        st.stop()

    ficha_title = meter_label(
        selected_row,
        key_column,
        system_column,
        name_column,
    )
    st.subheader(f"Ficha de revisión · {ficha_title}")

    action_message = st.session_state.pop("review_action_message", None)
    if action_message:
        st.success(str(action_message))

    if not reviews:
        review_summary(None)
        st.stop()

    def review_label(index: int) -> str:
        review = reviews[index]
        reviewed_at = review.get("reviewed_at") or "Sin fecha"
        quality = review.get("measurement_quality") or "Sin calidad"
        return f"{reviewed_at} — {quality}"

    selected_review_index = st.selectbox(
        "Revisión a visualizar",
        options=list(range(len(reviews))),
        format_func=review_label,
    )
    review = reviews[selected_review_index]

    action_edit, action_delete, action_space = st.columns([0.20, 0.20, 0.60])
    with action_edit:
        if st.button(
            "✏️ Editar registro",
            use_container_width=True,
            key=f"edit-review-{review.get('id')}",
        ):
            edit_review_dialog(review, review_repo)
    with action_delete:
        if st.button(
            "🗑️ Eliminar registro",
            use_container_width=True,
            key=f"delete-review-open-{review.get('id')}",
        ):
            delete_review_dialog(review, review_repo)

    review_summary(review)

    # Misma cabecera visual que la vista de captura.
    top_map, top_data = st.columns([0.48, 0.52], gap="large")
    with top_map:
        st.markdown("#### Ubicación del equipo")
        render_meter_map(selected_row, height=390)

    with top_data:
        st.markdown("#### Atributos de la geodatabase")
        readonly_snapshot(
            review.get("geodatabase_snapshot") or snapshot,
            title="Datos guardados con la revisión",
        )

    st.markdown("---")
    detail_col, control_col = st.columns(2, gap="large")

    with detail_col:
        st.markdown("### Detalle de la revisión")
        detail_rows = [
            ("Rectificación", review.get("rectification_status")),
            ("Equipo usado para rectificar", review.get("rectification_equipment")),
            ("Tipo de equipo", review.get("equipment_type")),
            ("Número de serie", review.get("equipment_serial")),
            ("Calidad", review.get("measurement_quality")),
            (
                "Último mantenimiento / revisión",
                review.get("last_maintenance_date"),
            ),
            ("Revisado por", review.get("reviewed_by")),
        ]
        st.dataframe(
            pd.DataFrame(detail_rows, columns=["Campo", "Valor"]),
            hide_index=True,
            width="stretch",
        )

        if review.get("notes"):
            st.markdown("**Observaciones adicionales**")
            st.write(review.get("notes"))

        measurement_latitude = review.get("measurement_latitude")
        measurement_longitude = review.get("measurement_longitude")
        if measurement_latitude is not None and measurement_longitude is not None:
            st.markdown("### Punto puntual de medición")
            render_measurement_point_map(
                float(measurement_latitude),
                float(measurement_longitude),
            )
            if review.get("measurement_location_notes"):
                st.caption(str(review.get("measurement_location_notes")))

        render_review_maintenance_status(review)

    with control_col:
        render_review_repairs_status(review)
        render_review_generalities(review)

    st.markdown("---")
    st.markdown("### Gráfico comparativo de mediciones")

    if (
        review.get("graph_source") == "sharepoint_link"
        and review.get("graph_original_url")
    ):
        cached_path = review.get("graph_storage_path")

        if cached_path:
            sync_left, sync_right = st.columns([0.72, 0.28])
            with sync_left:
                st.success("Estado del gráfico: sincronizado.")
            with sync_right:
                if st.button(
                    "Solicitar nueva sincronización",
                    key=f"resync-sharepoint-{review.get('id')}",
                    use_container_width=True,
                ):
                    try:
                        review_repo.mark_review_graph_pending(str(review.get("id")))
                        st.success("Nueva sincronización solicitada.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"No fue posible solicitar la sincronización: {exc}")
        else:
            st.info("Estado del gráfico: pendiente de importación automática.")

    render_graph_for_review(review, review_repo)

    st.markdown("---")
    st.markdown("### Historial del equipo")
    history = pd.DataFrame(reviews)
    wanted = [
        "reviewed_at",
        "measurement_quality",
        "equipment_type",
        "equipment_serial",
        "transducer_serial",
        "rectification_status",
        "maintenance_gel_applicable",
        "maintenance_gel_date",
        "maintenance_transducers_alignment_applicable",
        "maintenance_transducers_alignment_date",
        "maintenance_internal_download_date",
        "maintenance_simultaneous_installation_date",
        "maintenance_insertion_sensor_cleaning_date",
        "maintenance_solar_panel_applicable",
        "maintenance_solar_panel_cleaning_date",
        "maintenance_scada_working",
        "maintenance_scada_check_date",
        "repair_software_firmware_pending",
        "repair_perspective_pending",
        "repair_vision_cco_pending",
        "repair_vision_scada_vr2_pending",
        "repair_vision_reports_pending",
        "last_maintenance_date",
        "graph_source",
        "graph_original_url",
        "measurement_latitude",
        "measurement_longitude",
        "reviewed_by",
    ]
    existing = [column for column in wanted if column in history.columns]
    st.dataframe(history[existing], hide_index=True, width="stretch")


else:
    st.subheader("Diagnóstico de conexiones")
    st.write(
        "Esta vista prueba cada dependencia por separado. No modifica la geodatabase ni las revisiones."
    )
    st.caption(
        f"Fuente activa para el inventario: {settings.meter_data_source.upper()}"
    )

    sql_col, inv_col, rev_col, sp_col = st.columns(4)

    with sql_col:
        st.markdown("#### SQL Server / Geodatabase")
        if settings.demo_mode:
            status_badge("Modo demo: SQL no se consulta", "info")
        elif not settings.sql_configured:
            status_badge("No configurado", "warning")
        elif st.button("Probar SQL Server", use_container_width=True):
            ok, message = SqlMeterRepository(settings).ping()
            status_badge(message, "success" if ok else "error")
        st.caption("Normalmente se prueba dentro de la red AyA.")

    with inv_col:
        st.markdown("#### Supabase · inventario")
        if not settings.supabase_configured:
            status_badge("No configurado", "warning")
        elif st.button("Probar inventario", use_container_width=True):
            ok, message = get_supabase_meter_repo(settings).ping()
            status_badge(message, "success" if ok else "error")

    with rev_col:
        st.markdown("#### Supabase · revisiones")
        if not settings.supabase_configured:
            status_badge("No configurado", "warning")
        elif st.button("Probar revisiones", use_container_width=True):
            ok, message = get_supabase_repo(settings).ping()
            status_badge(message, "success" if ok else "error")

    with sp_col:
        st.markdown("#### Agente SharePoint")
        agent_status_summary = "No comprobado"
        if not settings.supabase_configured:
            status_badge("No es posible comprobarlo sin Supabase", "warning")
            agent_status_summary = "Sin comprobación"
        else:
            try:
                heartbeats = get_supabase_repo(settings).agent_heartbeats(
                    active_within_seconds=180
                )
                active_agents = [
                    item for item in heartbeats if item.get("active")
                ]

                if active_agents:
                    agent = active_agents[0]
                    host = str(agent.get("hostname") or "equipo sin nombre")
                    age = agent.get("age_seconds")
                    version = str(agent.get("version") or "—")
                    status_badge(f"Agente activo · {host}", "success")
                    if age is not None:
                        st.caption(
                            f"Última señal: hace {int(age)} s · Versión {version}"
                        )
                    else:
                        st.caption(f"Versión {version}")
                    agent_status_summary = f"Activo · {host}"
                elif heartbeats:
                    agent = heartbeats[0]
                    host = str(agent.get("hostname") or "equipo sin nombre")
                    age = agent.get("age_seconds")
                    status_badge("Agente registrado, pero sin actividad reciente", "warning")
                    if age is not None:
                        st.caption(
                            f"Última señal conocida: {host} · hace {int(age)} s"
                        )
                    else:
                        st.caption(f"Último equipo registrado: {host}")
                    agent_status_summary = "Registrado, inactivo"
                else:
                    status_badge("No se detecta un agente registrado", "warning")
                    st.caption(
                        "Streamlit Cloud no puede inspeccionar directamente la PC. "
                        "La comprobación se realiza mediante la señal de vida que "
                        "el agente publica en Supabase."
                    )
                    agent_status_summary = "No detectado"
            except Exception as exc:
                status_badge("No fue posible comprobar el agente", "error")
                st.caption(str(exc))
                agent_status_summary = "Error de comprobación"

    st.markdown("#### Estado de configuración")
    st.dataframe(
        pd.DataFrame(
            [
                {"Componente": "Fuente activa de inventario", "Configurado": settings.meter_data_source},
                {"Componente": "SQL Server", "Configurado": settings.sql_configured},
                {"Componente": "Supabase", "Configurado": settings.supabase_configured},
                {
                    "Componente": "Tabla inventario Supabase",
                    "Configurado": settings.supabase_meters_table,
                },
                {
                    "Componente": "Agente SharePoint",
                    "Configurado": agent_status_summary,
                },
                {"Componente": "Modo demo", "Configurado": settings.demo_mode},
                {
                    "Componente": "Contraseña de acceso",
                    "Configurado": bool(settings.app_password),
                },
            ]
        ),
        hide_index=True,
        width="stretch",
    )
