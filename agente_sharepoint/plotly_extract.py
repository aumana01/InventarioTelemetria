from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from typing import Any


PLOTLY_TARGET_VERSION = "3.0.1"
COMPACT_FORMAT = "plotly_json_gzip"
COMPACT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CompactGraph:
    filename: str
    content: bytes
    original_size: int
    compact_size: int
    figure_count: int


def _split_top_level_arguments(source: str) -> list[str]:
    args: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    depth_round = 0
    depth_square = 0
    depth_curly = 0

    for index, char in enumerate(source):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in ('"', "'", "`"):
            quote = char
            continue
        if char == "(":
            depth_round += 1
            continue
        if char == ")":
            if depth_round > 0:
                depth_round -= 1
            continue
        if char == "[":
            depth_square += 1
            continue
        if char == "]":
            if depth_square > 0:
                depth_square -= 1
            continue
        if char == "{":
            depth_curly += 1
            continue
        if char == "}":
            if depth_curly > 0:
                depth_curly -= 1
            continue

        if (
            char == ","
            and depth_round == 0
            and depth_square == 0
            and depth_curly == 0
        ):
            args.append(source[start:index].strip())
            start = index + 1

    args.append(source[start:].strip())
    return args


def _extract_call_body(source: str, open_paren: int) -> tuple[str, int]:
    quote: str | None = None
    escaped = False
    depth = 1

    for index in range(open_paren + 1, len(source)):
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in ('"', "'", "`"):
            quote = char
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[open_paren + 1 : index], index + 1

    raise ValueError("No se encontró el cierre de Plotly.newPlot(...).")


def extract_plotly_figures(html_text: str) -> list[dict[str, Any]]:
    marker = "Plotly.newPlot"
    figures: list[dict[str, Any]] = []
    position = 0

    while True:
        found = html_text.find(marker, position)
        if found < 0:
            break

        open_paren = html_text.find("(", found + len(marker))
        if open_paren < 0:
            break

        body, next_position = _extract_call_body(html_text, open_paren)
        position = next_position
        args = _split_top_level_arguments(body)
        if len(args) < 3:
            continue

        try:
            data = json.loads(args[1])
            layout = json.loads(args[2])
            config = json.loads(args[3]) if len(args) >= 4 else {}
        except json.JSONDecodeError:
            continue

        if not isinstance(data, list) or not isinstance(layout, dict):
            continue
        if not isinstance(config, dict):
            config = {}

        # El contenedor lo controla la aplicación, no el HTML original.
        layout = dict(layout)
        layout.pop("width", None)
        layout.pop("height", None)
        layout["autosize"] = True

        config = dict(config)
        config["responsive"] = True
        config.setdefault("displaylogo", False)

        figures.append(
            {
                "data": data,
                "layout": layout,
                "config": config,
            }
        )

    if not figures:
        raise ValueError(
            "No se encontró una llamada Plotly.newPlot con datos JSON extraíbles."
        )
    return figures


def compact_plotly_html(filename: str, html_content: bytes) -> CompactGraph:
    html_text = html_content.decode("utf-8", errors="replace")
    figures = extract_plotly_figures(html_text)

    payload = {
        "format": "plotly",
        "schema_version": COMPACT_SCHEMA_VERSION,
        "plotly_js_version": PLOTLY_TARGET_VERSION,
        "source_filename": filename,
        "figures": figures,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=9)

    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    compact_name = f"{base}.plotly.json.gz"

    return CompactGraph(
        filename=compact_name,
        content=compressed,
        original_size=len(html_content),
        compact_size=len(compressed),
        figure_count=len(figures),
    )
