from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from .core import normalize_value


def load_css(css_path: Path) -> None:
    if css_path.exists():
        st.html(f"<style>{css_path.read_text(encoding='utf-8')}</style>")


def readonly_snapshot(snapshot: Mapping[str, Any], title: str = "Datos de geodatabase") -> None:
    st.markdown(f"#### {title}")
    rows = []
    for key, value in snapshot.items():
        if key in {"X_CRTM05", "Y_CRTM05", "SRID_ORIGINAL", "EPSG_WGS84"}:
            continue
        rows.append({"Campo": str(key), "Valor": "" if value is None else str(normalize_value(value))})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=330)
    else:
        st.info("No hay atributos disponibles.")


def review_summary(review: Mapping[str, Any] | None) -> None:
    if not review:
        st.info("Este equipo todavía no tiene revisiones registradas en Supabase.")
        return
    ultrasonic = "Sí" if review.get("is_ultrasonic") else "No"
    cards = [
        ("Calidad", review.get("measurement_quality") or "—"),
        ("Rectificación", review.get("rectification_status") or "—"),
        ("Ultrasónico", ultrasonic),
        ("Último mantenimiento", review.get("last_maintenance_date") or "—"),
    ]
    cols = st.columns(4)
    for col, (label, value) in zip(cols, cards):
        col.metric(label, str(value))
    if review.get("failures"):
        st.markdown("**Fallas registradas:**")
        st.write(review.get("failures"))


def status_badge(text: str, kind: str = "info") -> None:
    safe = html.escape(text)
    st.html(f'<span class="status-badge status-{kind}">{safe}</span>')
