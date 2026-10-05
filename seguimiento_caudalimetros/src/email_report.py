"""Portable HTML report: table layouts and inline styles for mail clients."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from typing import Any, Mapping
from urllib.parse import urlsplit

import pandas as pd

from src.dashboard import GRAY, GREEN, LOCAL_ZONE, RED

MAX_HTML_BYTES = 90_000


@dataclass(frozen=True)
class EmailReport:
    html: str
    text: str
    total_rows: int
    shown_rows: int
    equipment_count: int


def safe_dashboard_url(value: str) -> str:
    value = str(value or "").strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            return ""
        if any(c in value for c in "\r\n\t"):
            return ""
        return value
    except ValueError:
        return ""


def _value(value: Any, limit: int = 600) -> str:
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    text = str(value).strip() or "—"
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _e(value: Any, limit: int = 600) -> str:
    return escape(_value(value, limit))


def build_email_report(frame: pd.DataFrame, *, title: str = "Seguimiento de caudalímetros",
                       scope: str = "Estado actual", filters: Mapping[str, Any] | None = None,
                       intro: str = "", author: str = "", dashboard_url: str = "",
                       max_rows: int = 50, generated_at: datetime | None = None) -> EmailReport:
    if frame.empty:
        raise ValueError("No hay resultados para generar el reporte.")
    if not 1 <= max_rows <= 200:
        raise ValueError("El límite de filas debe estar entre 1 y 200.")
    data = frame.copy()
    data["_priority"] = data["Semáforo"].map({RED: 0, GREEN: 1, GRAY: 2}).fillna(3)
    data = data.sort_values(["_priority", "Sistema", "Equipo"], kind="stable").drop(columns="_priority")
    timestamp = (generated_at or datetime.now(LOCAL_ZONE)).astimezone(LOCAL_ZONE)
    stamp = timestamp.strftime("%d/%m/%Y · %H:%M")
    url = safe_dashboard_url(dashboard_url)
    equipment_count = int(data["ID equipo"].nunique())
    red_count = int((data["Semáforo"] == RED).sum())
    green_count = int((data["Semáforo"] == GREEN).sum())
    gray_count = int((data["Semáforo"] == GRAY).sum())
    has_aspects = "Aspecto" in data.columns
    unit = "aspectos" if has_aspects else "registros"
    filter_pairs = [(str(k), ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v))
                    for k, v in (filters or {}).items() if v not in (None, "", [], ())]
    shown_count = min(max_rows, len(data))

    def compose(shown: pd.DataFrame) -> tuple[str, str]:
        cards = []
        for label, count, color in [("EQUIPOS", equipment_count, "#154e72"),
                                    ("ROJOS", red_count, "#9e312a"),
                                    ("VERDES", green_count, "#216d48"),
                                    ("NO APLICA", gray_count, "#596675")]:
            cards.append(f'<td style="padding:12px 6px;text-align:center;border:1px solid #dce4ec;">'
                         f'<div style="font-size:25px;font-weight:bold;color:{color};">{count}</div>'
                         f'<div style="font-size:10px;letter-spacing:1px;color:#586a7d;">{label}</div></td>')
        filters_html = "".join(f'<tr><td style="padding:5px 10px;color:#536678;width:35%;font-size:12px;">{_e(k, 100)}</td>'
                               f'<td style="padding:5px 10px;font-size:12px;color:#21384c;">{_e(v, 1600)}</td></tr>'
                               for k, v in filter_pairs)
        system_rows = []
        for system, group in data.groupby("Sistema", sort=True, dropna=False):
            system_rows.append(f'<tr><td style="padding:7px 10px;border-bottom:1px solid #e4eaf0;">{_e(system, 180)}</td>'
                               f'<td align="center" style="padding:7px;border-bottom:1px solid #e4eaf0;">{group["ID equipo"].nunique()}</td>'
                               f'<td align="center" style="padding:7px;color:#9e312a;border-bottom:1px solid #e4eaf0;">{int((group["Semáforo"] == RED).sum())}</td>'
                               f'<td align="center" style="padding:7px;color:#216d48;border-bottom:1px solid #e4eaf0;">{int((group["Semáforo"] == GREEN).sum())}</td></tr>')
        rows, text_rows = [], []
        for _, row in shown.iterrows():
            sem = row.get("Semáforo")
            bg, fg, badge = {RED: ("#fff1ef", "#9e312a", "ROJO"),
                             GREEN: ("#edf8f1", "#216d48", "VERDE"),
                             GRAY: ("#f1f4f7", "#596675", "NO APLICA")}.get(sem, ("#f1f4f7", "#596675", "SIN DATO"))
            aspect = row.get("Aspecto") if has_aspects else row.get("Detalle de pendientes")
            if not has_aspects and sem == GREEN:
                aspect = "Sin pendientes registrados"
            dates = f'Revisión: {_value(row.get("Fecha de revisión"))}'
            if has_aspects:
                dates += f' · Aspecto: {_value(row.get("Fecha del aspecto"))} · Vence: {_value(row.get("Vence"))}'
            rows.append(f'<tr bgcolor="{bg}" style="background-color:{bg};">'
                        f'<td style="padding:10px 8px;border-bottom:1px solid #dce4ec;vertical-align:top;">'
                        f'<strong>{_e(row.get("Equipo"), 180)}</strong><br><span style="font-size:10px;color:#586a7d;">'
                        f'{_e(row.get("ID equipo"), 80)} · {_e(row.get("Tipo de equipo"), 80)}</span></td>'
                        f'<td style="padding:10px 8px;border-bottom:1px solid #dce4ec;vertical-align:top;">{_e(row.get("Sistema"), 160)}</td>'
                        f'<td style="padding:10px 8px;border-bottom:1px solid #dce4ec;vertical-align:top;color:{fg};">'
                        f'<strong>{badge}</strong><br>{_e(row.get("Estado"), 180)}</td>'
                        f'<td style="padding:10px 8px;border-bottom:1px solid #dce4ec;vertical-align:top;">'
                        f'{_e(aspect)}<br><span style="font-size:10px;color:#586a7d;">{escape(dates)}</span></td></tr>')
            text_rows.append(f'{_value(row.get("Sistema"))} | {_value(row.get("Equipo"))} [{_value(row.get("ID equipo"))}] | '
                             f'{badge}: {_value(row.get("Estado"))} | {_value(aspect)} | {dates}')
        omitted = len(data) - len(shown)
        notice = (f'Se muestran {len(shown)} de {len(data)} {unit}, priorizando los rojos. '
                  f'El resumen incluye todos los resultados. Consulte el Dashboard para el detalle completo.') if omitted else (
                  f'Se incluyen los {len(data)} {unit} del reporte.')
        cta = (f'<p style="margin:22px 0;text-align:center;"><a href="{escape(url, quote=True)}" '
               'style="display:inline-block;background-color:#126998;color:#ffffff;text-decoration:none;padding:12px 24px;'
               'font-weight:bold;border-radius:6px;">Consultar Dashboard</a></p>') if url else ""
        introductory = escape(intro.strip()).replace("\n", "<br>") if intro.strip() else (
            "Se presenta el seguimiento de los equipos y sus necesidades de atención, según los filtros seleccionados.")
        author_html = f'<br>Preparado por: {_e(author, 160)}' if author.strip() else ""
        html = f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title, 200)}</title><style>@media only screen and (max-width:640px){{.report-container{{width:100%!important;}}.report-content{{padding:16px!important;}}.detail-table{{font-size:11px!important;}}}}</style></head>
<body style="margin:0;padding:0;background-color:#edf2f6;font-family:Arial,Helvetica,sans-serif;color:#24394b;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;background-color:#edf2f6;"><tr><td align="center" style="padding:24px 8px;">
<table class="report-container" role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:640px;max-width:100%;margin:0 auto;text-align:left;background-color:#ffffff;border:1px solid #dce4ec;">
<tr><td bgcolor="#123e59" style="background-color:#123e59;color:#ffffff;padding:26px 28px;">
<div style="font-size:11px;letter-spacing:2px;color:#b9dfef;">OS GAM · CAUDALES</div>
<h1 style="margin:10px 0 6px;font-size:25px;line-height:1.2;color:#ffffff;">{_e(title, 200)}</h1>
<div style="font-size:12px;color:#d3e5ef;">{escape(stamp)} · Costa Rica{author_html}</div></td></tr>
<tr><td class="report-content" style="padding:24px 28px;">
<p style="margin:0 0 18px;font-size:14px;line-height:1.6;">{introductory}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;table-layout:fixed;"><tr>{''.join(cards)}</tr></table>
<p style="font-size:11px;color:#637488;margin:9px 0 22px;">Los estados cuentan {unit}; un mismo equipo puede tener varios aspectos o revisiones.</p>
<h2 style="font-size:16px;color:#154e72;margin:22px 0 10px;">Alcance del reporte</h2>
<p style="font-size:13px;margin:0 0 10px;">{_e(scope, 200)}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;background-color:#f5f8fb;border:1px solid #e4eaf0;">{filters_html}</table>
<h2 style="font-size:16px;color:#154e72;margin:24px 0 10px;">Resumen por sistema</h2>
<table width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;font-size:12px;">
<tr bgcolor="#e9f1f7"><th align="left" style="padding:8px 10px;">Sistema</th><th style="padding:8px;">Equipos</th><th style="padding:8px;">Rojos</th><th style="padding:8px;">Verdes</th></tr>{''.join(system_rows)}</table>
<h2 style="font-size:16px;color:#154e72;margin:24px 0 10px;">Seguimiento y prioridades</h2>
<p style="font-size:12px;line-height:1.5;color:#536678;">{escape(notice)} Los textos extensos se resumen en el correo.</p>
<table class="detail-table" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;font-size:12px;line-height:1.45;table-layout:fixed;overflow-wrap:anywhere;">
<colgroup><col style="width:25%;"><col style="width:20%;"><col style="width:18%;"><col style="width:37%;"></colgroup>
<tr bgcolor="#e9f1f7"><th align="left" style="padding:9px 8px;">Equipo</th><th align="left" style="padding:9px 8px;">Sistema</th>
<th align="left" style="padding:9px 8px;">Estado</th><th align="left" style="padding:9px 8px;">Detalle y fechas</th></tr>{''.join(rows)}</table>
{cta}<p style="font-size:11px;line-height:1.6;color:#637488;margin:22px 0 0;">Rojo: requiere atención. Verde: vigente o sin pendiente. Gris: no aplica.<br>
Los vencimientos se evalúan a la fecha de generación del reporte.</p></td></tr>
<tr><td style="padding:16px 28px;border-top:1px solid #e4eaf0;font-size:11px;color:#637488;background-color:#f8fafc;">Seguimiento de caudalímetros · OS GAM<br>Reporte generado desde los resultados filtrados del Dashboard.</td></tr>
</table></td></tr></table></body></html>'''
        text = f'OS GAM · CAUDALES\n{title}\n{stamp} · Costa Rica\n{scope}\n'
        if author.strip():
            text += f'Preparado por: {author}\n'
        text += f'\n{intro.strip()}\nEquipos: {equipment_count} | Rojos: {red_count} | Verdes: {green_count} | No aplica: {gray_count}\n'
        text += '\nFiltros:\n' + '\n'.join(f'{k}: {v}' for k, v in filter_pairs)
        text += '\n\n' + notice + '\n\n' + '\n'.join(text_rows)
        if url:
            text += '\n\nConsultar Dashboard: ' + url
        return html, text

    while True:
        html, text = compose(data.iloc[:shown_count])
        if len(html.encode("utf-8")) <= MAX_HTML_BYTES:
            return EmailReport(html, text, len(data), shown_count, equipment_count)
        if shown_count <= 1:
            raise ValueError("El reporte es demasiado extenso. Reduzca los sistemas o filtros seleccionados.")
        shown_count = max(1, shown_count // 2)
