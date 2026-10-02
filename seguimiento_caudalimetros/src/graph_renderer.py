from __future__ import annotations

import streamlit as st

# El HTML del gráfico se coloca dentro de un iframe sandboxed. No se concede
# allow-same-origin, por lo que el JS del archivo no puede acceder al DOM padre.
_GRAPH_COMPONENT = st.components.v2.component(
    "caudalimetro_html_graph",
    html='<div class="graph-shell"><iframe class="graph-frame" title="Gráfico comparativo"></iframe></div>',
    css="""
        .graph-shell { width: 100%; min-height: 620px; }
        .graph-frame {
            width: 100%;
            height: 620px;
            border: 1px solid color-mix(in srgb, var(--st-text-color) 16%, transparent);
            border-radius: 12px;
            background: white;
        }
    """,
    js="""
        export default function({ data, parentElement }) {
            const frame = parentElement.querySelector('.graph-frame');
            frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-popups allow-downloads');
            frame.srcdoc = data?.html || '<p style="font-family:sans-serif;padding:1rem">Sin gráfico disponible.</p>';
        }
    """,
    isolate_styles=True,
)


def render_html_graph(html_bytes: bytes | str, key: str) -> None:
    if isinstance(html_bytes, bytes):
        html_text = html_bytes.decode("utf-8", errors="replace")
    else:
        html_text = html_bytes
    _GRAPH_COMPONENT(data={"html": html_text}, key=key)
