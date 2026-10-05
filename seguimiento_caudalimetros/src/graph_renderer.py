from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import plotly
import streamlit as st

_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
_PLOTLY_JS_PATH = Path(plotly.__file__).resolve().parent / "package_data" / "plotly.min.js"
_PLOTLY_JS = _PLOTLY_JS_PATH.read_text(encoding="utf-8")
_COMPONENT_JS = (
    _PLOTLY_JS
    + "\n"
    + (_ASSET_DIR / "graph_component.js").read_text(encoding="utf-8")
)

_GRAPH_COMPONENT = st.components.v2.component(
    "caudalimetro_html_graph",
    html=(_ASSET_DIR / "graph_component.html").read_text(encoding="utf-8"),
    css=(_ASSET_DIR / "graph_component.css").read_text(encoding="utf-8"),
    js=_COMPONENT_JS,
    isolate_styles=True,
)


def render_html_graph(
    html_bytes: bytes | str,
    key: str,
    height: int = 640,
) -> None:
    """Muestra HTML legado dentro de un iframe sandboxed."""
    if isinstance(html_bytes, bytes):
        html_text = html_bytes.decode("utf-8", errors="replace")
    else:
        html_text = html_bytes
    _GRAPH_COMPONENT(
        data={
            "mode": "html",
            "html": html_text,
            "height": max(360, min(int(height), 1000)),
        },
        key=key,
    )


def decode_compact_plotly(content: bytes) -> dict[str, Any]:
    try:
        raw = gzip.decompress(content)
    except OSError as exc:
        raise ValueError("El gráfico compacto no es un archivo gzip válido.") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("El gráfico compacto no contiene JSON válido.") from exc

    if payload.get("format") != "plotly":
        raise ValueError("El archivo no corresponde al formato Plotly compacto.")

    figures = payload.get("figures")
    if not isinstance(figures, list) or not figures:
        raise ValueError("El gráfico compacto no contiene figuras.")

    return payload


def render_plotly_graph(
    compact_bytes: bytes,
    key: str,
    height: int = 640,
) -> None:
    """Renderiza trazas/layout Plotly sin almacenar plotly.js en Supabase."""
    payload = decode_compact_plotly(compact_bytes)
    _GRAPH_COMPONENT(
        data={
            "mode": "plotly",
            "figures": payload.get("figures") or [],
            "height": max(360, min(int(height), 1000)),
            "plotlyVersion": payload.get("plotly_js_version"),
        },
        key=key,
    )
