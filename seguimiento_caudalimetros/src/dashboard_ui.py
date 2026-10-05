from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

import pandas as pd
import streamlit as st
from src.email_delivery import EmailAuditRepository, EmailSettings
from src.email_ui import render_email_module

from src.dashboard import (
    GRAY, GREEN, PERIODS, RED, build_dashboard_tables, export_csv,
    filter_dashboard, local_today, period_bounds, style_status_row,
)


def _choose(column, label: str, frame: pd.DataFrame, field: str) -> list[str]:
    options = sorted(frame[field].dropna().astype(str).unique().tolist())
    key = f"dashboard-filter-{field}"
    if key in st.session_state:
        st.session_state[key] = [v for v in st.session_state[key] if v in options]
    return column.multiselect(label, options, key=key, placeholder="Todos")


def render_dashboard(inventory: Sequence[Mapping[str, Any]], reviews: Sequence[Mapping[str, Any]], *,
                     email_settings: EmailSettings | None = None,
                     email_audit: EmailAuditRepository | None = None,
                     demo_mode: bool = False) -> None:
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
    red_count = int((result["Semáforo"] == RED).sum())
    green_count = int((result["Semáforo"] == GREEN).sum())
    metrics = st.columns(5)
    metrics[0].metric("Equipos en resultados", result["ID equipo"].nunique())
    metrics[1].metric("Aspectos encontrados" if detail else "Revisiones / equipos", len(result))
    metrics[2].metric("🔴 Rojos", red_count)
    metrics[3].metric("🟢 Verdes", green_count)
    metrics[4].metric("Equipos sin revisión", result.loc[result["Fecha de revisión"].isna(), "ID equipo"].nunique())
    st.subheader("Resultados filtrados")
    if result.empty:
        st.info("No hay resultados con la combinación de filtros seleccionada.")
        return

    front = ["ID equipo", "Sistema", "Equipo", "Tipo de equipo", "Semáforo", "Estado"]
    if detail:
        front += ["Categoría", "Aspecto", "Fecha del aspecto", "Vence", "Detalle"]
    else:
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
    st.caption("Puede ordenar las columnas y ampliar la tabla. Los contadores corresponden a los resultados filtrados.")
    st.download_button("Descargar resultados CSV", export_csv(table),
                       file_name=f"dashboard_caudalimetros_{today.isoformat()}.csv", mime="text/csv",
                       key="dashboard-download")
    report_filters = {"Período": period, "Fecha utilizada": date_field}
    if start:
        report_filters["Desde / hasta"] = f"{start:%d/%m/%Y} — {end:%d/%m/%Y}"
    report_filters.update({field: values for field, values in selections.items() if values})
    if query.strip():
        report_filters["Búsqueda"] = query.strip()
    report_filters["Incluir sin fecha"] = "Sí" if include_undated or not start else "No"
    if only_unreviewed and not history:
        report_filters["Solo equipos sin revisión"] = "Sí"
    render_email_module(result, context={"scope": ("Historial de revisiones" if history else "Estado actual · última revisión por equipo")
                                         + (" · Detalle por aspecto" if detail else " · Resumen por equipo"),
                                        "filters": report_filters},
                        settings=email_settings or EmailSettings.load(), audit=email_audit, demo_mode=demo_mode)
