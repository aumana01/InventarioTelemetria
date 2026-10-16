from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

import pandas as pd
import streamlit as st

from src.dashboard import (
    GRAY, GREEN, PERIODS, RED, TELEMETRY_ASPECTS,
    build_dashboard_tables, export_csv, filter_dashboard,
    filter_telemetry_pending, local_today, period_bounds, style_status_row,
)


def _choose(column, label: str, frame: pd.DataFrame, field: str) -> list[str]:
    options = sorted(frame[field].dropna().astype(str).unique().tolist())
    key = f"dashboard-filter-{field}"
    if key in st.session_state:
        st.session_state[key] = [v for v in st.session_state[key] if v in options]
    return column.multiselect(label, options, key=key, placeholder="Todos")


def render_dashboard(
    inventory: Sequence[Mapping[str, Any]],
    reviews: Sequence[Mapping[str, Any]],
) -> None:
    today = local_today()
    st.title("Dashboard")
    st.caption("Análisis de pendientes, mantenimiento y revisiones de caudalímetros.")

    c1, c2 = st.columns(2)
    history = c1.selectbox("Información a consultar", ["Estado actual · última revisión por equipo",
                                                    "Historial · todas las revisiones"],
                           key="dashboard-scope").startswith("Historial")
    detail = c2.selectbox("Tabla de resultados", ["Resumen por equipo", "Detalle por aspecto"],
                          key="dashboard-table") == "Detalle por aspecto"
    summary, aspects = build_dashboard_tables(inventory, reviews, history=history, today=today)
    frame = aspects if detail else summary
    if history:
        st.caption("Cada fila corresponde a una revisión histórica. Los vencimientos se evalúan a la fecha de hoy.")
    else:
        st.caption("Se toma la última revisión global de cada equipo antes de aplicar filtros. Incluye equipos sin revisión.")
    st.caption("Rojo: pendiente, vencido, sin fecha, calidad regular/mala o rectificación sin realizar. "
               "Verde: vigente o sin pendiente. Gris: no aplica. El resumen es rojo si tiene al menos un aspecto rojo.")

    with st.container(border=True):
        p1, p2, p3 = st.columns([1.1, 1.1, 1.8])
        period = p1.selectbox("Período", PERIODS, key="dashboard-period")
        date_fields = ["Fecha de revisión", "Último mantenimiento"]
        if detail:
            date_fields += ["Fecha del aspecto", "Vence"]
        if st.session_state.get("dashboard-date-field") not in date_fields:
            st.session_state["dashboard-date-field"] = date_fields[0]
        date_field = p2.selectbox("Aplicar período sobre", date_fields, key="dashboard-date-field")
        specific, custom = None, None
        if period == "Fecha específica":
            specific = p3.date_input("Fecha específica", value=today, key="dashboard-specific")
        elif period == "Rango personalizado":
            chosen = p3.date_input("Desde / hasta", value=(date(today.year, 1, 1), today), key="dashboard-range")
            if len(chosen) == 2:
                custom = chosen
        else:
            p3.caption("Los períodos son móviles y terminan hoy, según la fecha de Costa Rica.")
        try:
            start, end = period_bounds(period, today, specific=specific, custom=custom)
        except ValueError as exc:
            st.info(str(exc))
            return
        include_undated = st.checkbox("Incluir registros sin fecha en el período",
                                     disabled=period == "Todo el historial", key="dashboard-undated",
                                     help="Permite conservar equipos sin revisión o mantenimientos sin fecha.")
        if start:
            st.caption(f"Del {start:%d/%m/%Y} al {end:%d/%m/%Y}, inclusive.")

        st.markdown("#### Seguimiento especializado · Área de Telemetría")
        telemetry_only = st.checkbox(
            "Solo casos pendientes del Área de Telemetría",
            key="dashboard-telemetry-only",
            help=(
                "Filtra exclusivamente señal, Perspective, Vision Client CCO, "
                "Vision Client SCADA vr2 y descarga del módulo de reportes "
                "cuando están marcados en rojo como pendientes."
            ),
        )
        selected_telemetry_aspects = list(TELEMETRY_ASPECTS)
        if telemetry_only:
            selected_telemetry_aspects = st.multiselect(
                "Tipos de pendientes de Telemetría",
                options=list(TELEMETRY_ASPECTS),
                default=list(TELEMETRY_ASPECTS),
                key="dashboard-telemetry-aspects",
                help=(
                    "Puede seleccionar uno o varios. Si no selecciona ninguno, "
                    "no se mostrarán casos."
                ),
            )
            st.caption(
                "Se consideran únicamente los aspectos pendientes (rojos) "
                "del Área de Telemetría. Los demás pendientes no cuentan para "
                "este filtro."
            )

        f1, f2, f3, f4 = st.columns(4)
        selections = {
            "Sistema": _choose(f1, "Sistema de abastecimiento", frame, "Sistema"),
            "Tipo de equipo": _choose(f2, "Tipo de equipo", frame, "Tipo de equipo"),
            "Semáforo": _choose(f3, "Semáforo · rojos / verdes", frame, "Semáforo"),
            "Estado": _choose(f4, "Estado", frame, "Estado"),
        }
        query = st.text_input("Buscar equipo, código, serie, observaciones o pendiente",
                              key="dashboard-search", placeholder="Escriba uno o varios términos")
        with st.expander("Más filtros"):
            a1, a2, a3 = st.columns(3)
            selections.update({
                "Calidad": _choose(a1, "Calidad de medición", frame, "Calidad"),
                "Rectificación": _choose(a2, "Rectificación", frame, "Rectificación"),
                "Revisado por": _choose(a3, "Revisado por", frame, "Revisado por"),
                "Estado inventario": _choose(a1, "Estado en inventario", frame, "Estado inventario"),
                "Gráfico": _choose(a2, "Estado del gráfico", frame, "Gráfico"),
                "ID equipo": _choose(a3, "Código de equipo", frame, "ID equipo"),
            })
            if detail:
                selections["Categoría"] = _choose(a1, "Mantenimiento / reparación / control", frame, "Categoría")
                selections["Aspecto"] = _choose(a2, "Aspecto específico", frame, "Aspecto")
            only_unreviewed = st.checkbox("Solo equipos sin revisión", disabled=history, key="dashboard-unreviewed")
        if st.button("Limpiar filtros", key="dashboard-reset"):
            for key in list(st.session_state):
                if key.startswith("dashboard-") and key not in {"dashboard-scope", "dashboard-table"}:
                    del st.session_state[key]
            st.rerun()

    result = filter_dashboard(frame, selections=selections, start=start, end=end,
                              date_column=date_field, include_undated=include_undated, query=query,
                              only_unreviewed=only_unreviewed and not history)
    if telemetry_only:
        result = filter_telemetry_pending(result, aspects, selected_telemetry_aspects)
    red_count = int((result["Semáforo"] == RED).sum())
    green_count = int((result["Semáforo"] == GREEN).sum())
    metrics = st.columns(5)
    metrics[0].metric(
        "Equipos con pendientes de Telemetría" if telemetry_only else "Equipos en resultados",
        result["ID equipo"].nunique(),
    )
    metrics[1].metric("Aspectos encontrados" if detail else "Revisiones / equipos", len(result))
    if telemetry_only:
        telemetry_total = (len(result) if detail else
                           int(result["Pendientes Telemetría"].sum()))
        metrics[2].metric("🔴 Pendientes Telemetría", telemetry_total)
        metrics[3].metric("Tipos seleccionados", len(selected_telemetry_aspects))
    else:
        metrics[2].metric("🔴 Rojos", red_count)
        metrics[3].metric("🟢 Verdes", green_count)
    metrics[4].metric(
        "Equipos sin revisión",
        result.loc[result["Fecha de revisión"].isna(), "ID equipo"].nunique(),
    )
    st.subheader("Resultados filtrados")
    if result.empty:
        st.info("No hay resultados con la combinación de filtros seleccionada.")
        return

    front = ["ID equipo", "Sistema", "Equipo", "Tipo de equipo", "Semáforo", "Estado"]
    if detail:
        front += ["Categoría", "Aspecto", "Fecha del aspecto", "Vence", "Detalle"]
    else:
        if telemetry_only:
            front += ["Pendientes Telemetría", "Detalle pendientes Telemetría"]
        front += ["Pendientes rojos", "Aspectos verdes", "Detalle de pendientes"]
    table = result.drop(columns="Registro")
    table = table[front + [c for c in table.columns if c not in front]]
    # pandas Styler's default max_elements can silently omit rows in large histories.
    with pd.option_context("styler.render.max_elements", max(262144, table.size + 1)):
        styled = table.style.apply(style_status_row, axis=1)
        st.dataframe(styled, hide_index=True, width="stretch", height=560,
                     column_config={field: st.column_config.DateColumn(field, format="DD/MM/YYYY")
                                    for field in ["Fecha de revisión", "Último mantenimiento", "Fecha del aspecto", "Vence"]
                                    if field in table.columns})
    if telemetry_only and not detail:
        st.caption(
            "El semáforo general y las columnas de pendientes totales mantienen "
            "la valoración integral del equipo; las columnas de Telemetría "
            "consideran solo los aspectos especializados seleccionados."
        )
    st.caption("Puede ordenar las columnas y ampliar la tabla. Los contadores corresponden a los resultados filtrados.")
    st.download_button("Descargar resultados CSV", export_csv(table),
                       file_name=f"dashboard_caudalimetros_{today.isoformat()}.csv", mime="text/csv",
                       key="dashboard-download")
