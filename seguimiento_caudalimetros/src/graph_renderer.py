from __future__ import annotations

from pathlib import Path

import streamlit as st

_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"

_GRAPH_COMPONENT = st.components.v2.component(
    "caudalimetro_html_graph",
    html=(_ASSET_DIR / "graph_component.html").read_text(encoding="utf-8"),
    css=(_ASSET_DIR / "graph_component.css").read_text(encoding="utf-8"),
    js=(_ASSET_DIR / "graph_component.js").read_text(encoding="utf-8"),
    isolate_styles=True,
)


def render_html_graph(html_bytes: bytes | str, key: str) -> None:
    """Muestra HTML de terceros dentro de un iframe sandboxed.

    El HTML se envía como datos al componente y nunca como código del propio
    componente Streamlit. El iframe no tiene allow-same-origin ni acceso al DOM
    padre.
    """
    if isinstance(html_bytes, bytes):
        html_text = html_bytes.decode("utf-8", errors="replace")
    else:
        html_text = html_bytes
    _GRAPH_COMPONENT(data={"html": html_text}, key=key)
