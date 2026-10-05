from __future__ import annotations

import hmac
import re
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.config import Settings
from src.core import (
    QUALITY_VALUES,
    RECTIFICATION_VALUES,
    determine_key_column,
    determine_key_column_from_frame,
    parse_measurement_coordinates,
    parse_sharepoint_attachment_url,
    snapshot_from_row,
    validate_html_file,
    validate_review,
)
from src.graph_renderer import render_html_graph
from src.sharepoint_repository import SharePointListRepository
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


@st.cache_resource
def get_sharepoint_repo(current_settings: Settings) -> SharePointListRepository:
    return SharePointListRepository(current_settings)


@st.cache_data(ttl=300, show_spinner=False)
def cached_sharepoint_items(_repo: SharePointListRepository) -> list[dict[str, Any]]:
    return _repo.list_items(limit=5000)


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


def render_meter_map(row: pd.Series) -> None:
    lat = row.get("LATITUD")
    lon = row.get("LONGITUD")
    if pd.isna(lat) or pd.isna(lon):
        st.warning("El punto seleccionado no tiene coordenadas WGS84 utilizables.")
        return
    map_df = pd.DataFrame({"lat": [float(lat)], "lon": [float(lon)]})
    st.map(
        map_df,
        latitude="lat",
        longitude="lon",
        color="#0072BC",
        size=45,
        zoom=16,
        width="stretch",
        height=500,
    )
    st.caption(f"WGS84: {float(lat):.6f}, {float(lon):.6f}")


def render_measurement_point_map(latitude: float, longitude: float) -> None:
    point_df = pd.DataFrame({"lat": [float(latitude)], "lon": [float(longitude)]})
    st.map(
        point_df,
        latitude="lat",
        longitude="lon",
        color="#0072BC",
        size=38,
        zoom=16,
        width="stretch",
        height=300,
    )
    st.caption(
        f"Punto puntual de medición · WGS84: {float(latitude):.6f}, {float(longitude):.6f}"
    )


def get_review_repo() -> SupabaseReviewRepository | None:
    if not settings.supabase_configured:
        return None
    return get_supabase_repo(settings)


def get_sp_repo() -> SharePointListRepository | None:
    if not settings.sharepoint_configured:
        return None
    return get_sharepoint_repo(settings)


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
            render_html_graph(content, key=f"manual-{review.get('id', path)}")
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
                st.caption("Vista directa desde la copia de visualización almacenada en Supabase.")
                render_html_graph(
                    content,
                    key=f"sharepoint-link-cache-{review.get('id', cached_path)}",
                )
                return
            except Exception as exc:
                st.warning(f"No fue posible abrir la copia HTML almacenada: {exc}")

        item_id = review.get("sharepoint_item_id")
        sp_repo = get_sp_repo()
        if item_id and sp_repo is not None:
            try:
                filename, content = sp_repo.download_html_attachment(int(item_id))
                st.caption(
                    f"Vista recuperada por API desde Microsoft List ID {item_id} · {filename}"
                )
                render_html_graph(
                    content,
                    key=f"sharepoint-link-api-{item_id}-{review.get('id', '')}",
                )
                return
            except Exception as exc:
                st.warning(
                    "El vínculo quedó guardado, pero la recuperación automática por API "
                    f"no fue posible: {exc}"
                )

        st.info(
            "El vínculo original está conservado. Para verlo directamente dentro de la ficha "
            "sin API, adjunte también una copia del archivo HTML al registrar la revisión. "
            "SharePoint puede forzar la descarga o requerir autenticación y por eso un iframe "
            "directo al vínculo no es confiable."
        )
        return

    if source == "sharepoint":
        item_id = review.get("sharepoint_item_id")
        if not item_id:
            st.info("La revisión no tiene ID de Microsoft List asociado.")
            return
        sp_repo = get_sp_repo()
        if sp_repo is None:
            st.warning(
                "La referencia al Microsoft List está guardada, pero la integración REST "
                "no está configurada en este despliegue."
            )
            return
        try:
            filename, content = sp_repo.download_html_attachment(int(item_id))
            st.caption(f"Microsoft List ID {item_id} · {filename}")
            render_html_graph(content, key=f"sharepoint-{item_id}-{review.get('id', '')}")
        except Exception as exc:
            st.error(f"No fue posible cargar el adjunto HTML de Microsoft List: {exc}")
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
    left, right = st.columns([0.44, 0.56], gap="large")

    with left:
        st.subheader("Ubicación del equipo")
        render_meter_map(selected_row)
        with st.expander("Ver atributos de la geodatabase", expanded=True):
            readonly_snapshot(snapshot)

    with right:
        st.subheader("Formulario de revisión")
        if selected_system_name:
            st.markdown(f"**Sistema de Abastecimiento:** {selected_system_name}")
        st.markdown(f"**Equipo:** {selected_meter_name or 'Sin nombre registrado'}")

        rectification_status = st.radio(
            "¿El equipo se ha logrado rectificar con otro equipo de forma simultánea?",
            options=list(RECTIFICATION_VALUES),
            horizontal=False,
        )
        rectification_equipment = ""
        if rectification_status == "Sí, con medición simultánea":
            rectification_equipment = st.text_input(
                "¿Con cuál equipo se realizó la rectificación?",
                placeholder="Ej.: ultrasónico portátil / marca-modelo / código interno",
            )

        is_ultrasonic = st.checkbox("Es un equipo ultrasónico")
        circumference_mm = None
        wall_thickness_mm = None
        transducer_distance_mm = None
        if is_ultrasonic:
            c1, c2, c3 = st.columns(3)
            circumference_mm = c1.number_input(
                "Circunferencia [mm]", min_value=0.0, step=0.1, format="%.2f"
            )
            wall_thickness_mm = c2.number_input(
                "Espesor [mm]", min_value=0.0, step=0.1, format="%.2f"
            )
            transducer_distance_mm = c3.number_input(
                "Distancia transductores [mm]", min_value=0.0, step=0.1, format="%.2f"
            )

        measurement_quality = st.selectbox(
            "Calidad de medición",
            options=list(QUALITY_VALUES),
            index=1,
        )

        last_maintenance_date = st.date_input(
            "Fecha del último mantenimiento / revisión",
            value=None,
            max_value=date.today(),
        )
        failures = st.text_area(
            "Fallas que ha presentado el equipo",
            placeholder="Describa fallas, intermitencias, errores, desviaciones u observaciones técnicas.",
            height=120,
        )
        reviewed_by = st.text_input("Revisado por", placeholder="Nombre o usuario responsable")

        st.markdown("#### Punto de medición puntual")
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

        st.markdown("#### Gráfico comparativo")
        graph_options = [
            "Sin gráfico",
            "Cargar archivo HTML",
            "Vínculo MS List / SharePoint",
        ]
        if settings.sharepoint_configured:
            graph_options.append("Microsoft List (API)")
        graph_option = st.radio("Origen del gráfico", graph_options, horizontal=False)

        uploaded_html = None
        sharepoint_cached_html = None
        sharepoint_url = ""
        sharepoint_item_id = None
        sharepoint_file_name = None

        if graph_option == "Cargar archivo HTML":
            uploaded_html = st.file_uploader(
                "Archivo HTML de comparación",
                type=["html", "htm"],
                help="Se almacenará en un bucket privado de Supabase y se mostrará dentro de la ficha.",
            )
            if uploaded_html:
                validation = validate_html_file(uploaded_html.name, uploaded_html.getvalue())
                if validation.ok:
                    status_badge("HTML válido para carga", "success")
                else:
                    for error in validation.errors:
                        st.error(error)

        elif graph_option == "Vínculo MS List / SharePoint":
            sharepoint_url = st.text_input(
                "Hipervínculo del archivo HTML en Microsoft List / SharePoint",
                placeholder="https://...sharepoint.com/.../Attachments/2324/grafico.html?web=1",
            )
            parsed_link = parse_sharepoint_attachment_url(sharepoint_url)
            if sharepoint_url.strip():
                if parsed_link is None:
                    st.warning(
                        "El vínculo debe ser HTTPS y pertenecer a un dominio *.sharepoint.com."
                    )
                else:
                    if parsed_link.get("item_id"):
                        st.caption(
                            f"ID de Microsoft List detectado: {parsed_link['item_id']} · "
                            f"Archivo: {parsed_link.get('file_name') or 'no identificado'}"
                        )
                    else:
                        st.caption(
                            "El vínculo se guardará, aunque no se pudo extraer automáticamente "
                            "el ID del elemento."
                        )

            sharepoint_cached_html = st.file_uploader(
                "Copia HTML para visualizar dentro del aplicativo (opcional)",
                type=["html", "htm"],
                key="sharepoint_cached_html",
                help=(
                    "El vínculo original siempre se conserva. Si adjunta aquí el mismo HTML, "
                    "Supabase guarda una copia de visualización y la ficha puede abrirlo directamente "
                    "sin descargarlo al escritorio."
                ),
            )
            if sharepoint_cached_html:
                validation = validate_html_file(
                    sharepoint_cached_html.name,
                    sharepoint_cached_html.getvalue(),
                )
                if validation.ok:
                    status_badge("Copia HTML válida para visualización directa", "success")
                else:
                    for error in validation.errors:
                        st.error(error)

        elif graph_option == "Microsoft List (API)":
            sp_repo = get_sp_repo()
            if sp_repo is not None:
                try:
                    items = cached_sharepoint_items(sp_repo)
                    if items:
                        item_ids = [int(x["Id"]) for x in items]
                        labels = {
                            int(x["Id"]): f"{x['Id']} — {x.get('Title') or 'Sin título'}"
                            for x in items
                        }
                        sharepoint_item_id = st.selectbox(
                            "ID de Seguimiento de Detección de Fugas GAM",
                            options=item_ids,
                            format_func=lambda x: labels.get(x, str(x)),
                        )
                        st.caption(
                            "Al guardar se valida que el ID tenga un adjunto .html/.htm. "
                            "El archivo no se copia a Supabase; se conserva solamente la referencia."
                        )
                    else:
                        st.warning("Microsoft List no devolvió registros.")
                except Exception as exc:
                    st.error(f"No fue posible consultar Microsoft List: {exc}")

        notes = st.text_area("Observaciones adicionales", height=90)

        save_disabled = not settings.supabase_configured
        if save_disabled:
            st.warning(
                "Supabase no está configurado. El formulario puede revisarse, pero no se habilita el guardado."
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
                "is_ultrasonic": is_ultrasonic,
                "circumference_mm": circumference_mm,
                "wall_thickness_mm": wall_thickness_mm,
                "transducer_distance_mm": transducer_distance_mm,
                "measurement_quality": measurement_quality,
            }
            validation = validate_review(data)
            errors = list(validation.errors)

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
                        uploaded_html.name, uploaded_html.getvalue()
                    )
                    errors.extend(html_validation.errors)
                    graph_source = "manual"

            elif graph_option == "Vínculo MS List / SharePoint":
                parsed_link = parse_sharepoint_attachment_url(sharepoint_url)
                if not sharepoint_url.strip():
                    errors.append("Ingrese el hipervínculo del archivo HTML en Microsoft List.")
                elif parsed_link is None:
                    errors.append(
                        "El hipervínculo debe ser HTTPS y pertenecer a un dominio *.sharepoint.com."
                    )
                else:
                    graph_source = "sharepoint_link"
                    sharepoint_item_id = parsed_link.get("item_id")
                    sharepoint_file_name = parsed_link.get("file_name")
                    if sharepoint_cached_html is not None:
                        html_validation = validate_html_file(
                            sharepoint_cached_html.name,
                            sharepoint_cached_html.getvalue(),
                        )
                        errors.extend(html_validation.errors)

            elif graph_option == "Microsoft List (API)":
                if sharepoint_item_id is None:
                    errors.append("Seleccione un ID de Microsoft List.")
                else:
                    graph_source = "sharepoint"

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

                        if (
                            graph_source == "sharepoint_link"
                            and sharepoint_cached_html is not None
                        ):
                            graph_storage_path = review_repo.upload_html(
                                equipment_key=equipment_key,
                                filename=sharepoint_cached_html.name,
                                content=sharepoint_cached_html.getvalue(),
                            )

                        if graph_source == "sharepoint" and sharepoint_item_id is not None:
                            sp_repo = get_sp_repo()
                            if sp_repo is None:
                                raise RuntimeError(
                                    "La integración REST con Microsoft List no está configurada."
                                )
                            sharepoint_file_name, _ = sp_repo.download_html_attachment(
                                int(sharepoint_item_id)
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
                            "is_ultrasonic": bool(is_ultrasonic),
                            "circumference_mm": circumference_mm if is_ultrasonic else None,
                            "wall_thickness_mm": wall_thickness_mm if is_ultrasonic else None,
                            "transducer_distance_mm": (
                                transducer_distance_mm if is_ultrasonic else None
                            ),
                            "measurement_quality": measurement_quality,
                            "graph_source": graph_source,
                            "graph_storage_path": graph_storage_path,
                            "sharepoint_item_id": sharepoint_item_id,
                            "sharepoint_file_name": sharepoint_file_name,
                            "last_maintenance_date": (
                                last_maintenance_date.isoformat()
                                if last_maintenance_date
                                else None
                            ),
                            "failures": failures.strip() or None,
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

                        saved = review_repo.insert_review(payload)
                        st.success(
                            f"Revisión guardada correctamente. ID: {saved.get('id', 'registrado')}"
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

    review_summary(review)

    c1, c2 = st.columns([0.48, 0.52], gap="large")
    with c1:
        st.markdown("#### Ubicación")
        render_meter_map(selected_row)

        measurement_latitude = review.get("measurement_latitude")
        measurement_longitude = review.get("measurement_longitude")
        if measurement_latitude is not None and measurement_longitude is not None:
            st.markdown("**Punto puntual de medición registrado en esta revisión**")
            render_measurement_point_map(
                float(measurement_latitude),
                float(measurement_longitude),
            )
            if review.get("measurement_location_notes"):
                st.caption(str(review.get("measurement_location_notes")))

        with st.expander("Atributos de la geodatabase guardados con la revisión", expanded=True):
            readonly_snapshot(review.get("geodatabase_snapshot") or snapshot)

        st.markdown("#### Detalle técnico")
        detail_rows = [
            ("Rectificación", review.get("rectification_status")),
            ("Equipo usado para rectificar", review.get("rectification_equipment")),
            ("Equipo ultrasónico", "Sí" if review.get("is_ultrasonic") else "No"),
            ("Circunferencia [mm]", review.get("circumference_mm")),
            ("Espesor [mm]", review.get("wall_thickness_mm")),
            ("Distancia de transductores [mm]", review.get("transducer_distance_mm")),
            ("Calidad", review.get("measurement_quality")),
            ("Latitud punto de medición", review.get("measurement_latitude")),
            ("Longitud punto de medición", review.get("measurement_longitude")),
            ("Referencia punto de medición", review.get("measurement_location_notes")),
            ("Último mantenimiento / revisión", review.get("last_maintenance_date")),
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

    with c2:
        st.markdown("#### Gráfico comparativo de mediciones")
        render_graph_for_review(review, review_repo)

    st.markdown("#### Historial del equipo")
    history = pd.DataFrame(reviews)
    wanted = [
        "reviewed_at",
        "measurement_quality",
        "rectification_status",
        "is_ultrasonic",
        "last_maintenance_date",
        "graph_source",
        "graph_original_url",
        "measurement_latitude",
        "measurement_longitude",
        "reviewed_by",
        "failures",
    ]
    existing = [c for c in wanted if c in history.columns]
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
        st.markdown("#### Microsoft List")
        if not settings.sharepoint_configured:
            status_badge("Integración REST no configurada", "info")
        elif st.button("Probar Microsoft List", use_container_width=True):
            ok, message = get_sharepoint_repo(settings).ping()
            status_badge(message, "success" if ok else "error")

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
                    "Componente": "Microsoft List / SharePoint REST",
                    "Configurado": settings.sharepoint_configured,
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
