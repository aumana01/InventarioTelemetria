from __future__ import annotations

import json
import logging
import os
import re
import socket
import sys
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse
from uuid import uuid4


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "agent_secrets.toml"
STATE_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AyA" / "AgenteSharePointCaudalimetros"
PROFILE_DIR = STATE_DIR / "edge_profile"
LOG_PATH = STATE_DIR / "agent.log"
SINGLETON_PORT = 39571
AGENT_VERSION = "1.1.0"


@dataclass(frozen=True)
class Config:
    supabase_url: str
    supabase_key: str
    table: str
    bucket: str
    site_url: str
    poll_seconds: int


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"No existe {CONFIG_PATH.name}. Copie agent_secrets.example.toml "
            "a agent_secrets.toml y complete los datos."
        )
    with CONFIG_PATH.open("rb") as handle:
        data = tomllib.load(handle)
    sb = data.get("supabase") or {}
    sp = data.get("sharepoint") or {}
    agent = data.get("agent") or {}
    config = Config(
        supabase_url=str(sb.get("url") or "").strip(),
        supabase_key=str(sb.get("service_role_key") or "").strip(),
        table=str(sb.get("table") or "caudalimetro_revisiones").strip(),
        bucket=str(sb.get("bucket") or "caudalimetros-graficos").strip(),
        site_url=str(sp.get("site_url") or "").strip().rstrip("/"),
        poll_seconds=max(15, int(agent.get("poll_seconds") or 60)),
    )
    if not config.supabase_url or not config.supabase_key or not config.site_url:
        raise ValueError(
            "Complete supabase.url, supabase.service_role_key y sharepoint.site_url."
        )
    return config


def setup_logging() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def singleton_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", SINGLETON_PORT))
    except OSError as exc:
        raise RuntimeError("El agente ya parece estar ejecutándose.") from exc
    sock.listen(1)
    return sock


def safe_filename(value: str) -> str:
    name = Path(value or "grafico.html").name
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return clean or "grafico.html"


def parse_attachment(url: str) -> tuple[int | None, str]:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.netloc.lower().endswith(".sharepoint.com"):
        raise ValueError("El vínculo no pertenece a SharePoint.")
    match = re.search(r"/Attachments/(\d+)/([^/?#]+)", parsed.path, re.IGNORECASE)
    if not match:
        return None, Path(unquote(parsed.path)).name or "grafico_sharepoint.html"
    return int(match.group(1)), unquote(match.group(2))


def canonical_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def login_url(url: str) -> bool:
    host = urlparse(str(url or "")).netloc.lower()
    return any(
        value in host
        for value in (
            "login.microsoftonline.com",
            "login.microsoft.com",
            "login.live.com",
        )
    )


class Repository:
    def __init__(self, config: Config):
        from supabase import create_client
        self.config = config
        self.client = create_client(config.supabase_url, config.supabase_key)

    def pending(self, limit: int = 100) -> list[dict]:
        result = (
            self.client.table(self.config.table)
            .select("*")
            .eq("graph_source", "sharepoint_link")
            .not_.is_("graph_original_url", "null")
            .is_("graph_storage_path", "null")
            .order("reviewed_at", desc=False)
            .limit(limit)
            .execute()
        )
        return getattr(result, "data", None) or []

    def upload(self, equipment_key: str, filename: str, content: bytes) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = (
            f"{safe_filename(equipment_key)}/"
            f"{stamp}_{uuid4().hex[:8]}_{safe_filename(filename)}"
        )
        self.client.storage.from_(self.config.bucket).upload(
            path=path,
            file=content,
            file_options={
                "content-type": "text/html; charset=utf-8",
                "upsert": "false",
            },
        )
        return path

    def mark_synced(self, review_id: str, path: str, filename: str) -> None:
        (
            self.client.table(self.config.table)
            .update(
                {
                    "graph_storage_path": path,
                    "sharepoint_file_name": filename,
                }
            )
            .eq("id", str(review_id))
            .execute()
        )

    def heartbeat(self, status: str = "active", detail: str | None = None) -> None:
        hostname = socket.gethostname() or "equipo-sin-nombre"
        payload = {
            "agent": "agente_sharepoint",
            "version": AGENT_VERSION,
            "hostname": hostname,
            "status": status,
            "detail": detail,
            "last_seen_utc": datetime.now(timezone.utc).isoformat(),
            "poll_seconds": self.config.poll_seconds,
        }
        path = f"agent_status/{safe_filename(hostname)}.json"
        self.client.storage.from_(self.config.bucket).upload(
            path=path,
            file=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            file_options={
                "content-type": "application/json; charset=utf-8",
                "upsert": "true",
            },
        )


def open_context(playwright, headless: bool):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="msedge",
        headless=headless,
        accept_downloads=True,
    )


def wait_for_login(page, site_url: str, timeout_seconds: int = 600) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not login_url(page.url):
            try:
                page.goto(site_url, wait_until="domcontentloaded", timeout=90_000)
                if not login_url(page.url):
                    return True
            except Exception:
                pass
        time.sleep(2)
    return False


def authenticated_context(playwright, site_url: str):
    context = open_context(playwright, headless=True)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.goto(site_url, wait_until="domcontentloaded", timeout=90_000)
        if not login_url(page.url):
            return context, page
    except Exception:
        pass
    context.close()

    logging.warning("La sesión Microsoft 365 requiere autenticación.")
    context = open_context(playwright, headless=False)
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(site_url, wait_until="domcontentloaded", timeout=90_000)
    if login_url(page.url):
        logging.info("Complete el inicio de sesión/MFA en la ventana de Edge.")
        if not wait_for_login(page, site_url):
            context.close()
            raise RuntimeError("Tiempo agotado esperando autenticación Microsoft 365.")
    return context, page


def fetch_html(page, url: str) -> tuple[str, bytes]:
    _, filename = parse_attachment(url)
    target = canonical_url(url)
    result = page.evaluate(
        """async (targetUrl) => {
            const response = await fetch(targetUrl, {
                method: "GET",
                credentials: "include",
                cache: "no-store"
            });
            const text = await response.text();
            return {
                ok: response.ok,
                status: response.status,
                url: response.url,
                text
            };
        }""",
        target,
    )
    status = int(result.get("status") or 0)
    if status in (401, 403):
        raise PermissionError(f"SharePoint respondió HTTP {status}.")
    if not result.get("ok"):
        raise RuntimeError(f"SharePoint respondió HTTP {status}.")

    text = str(result.get("text") or "")
    sample = text[:300_000].lower()
    if "login.microsoftonline.com" in sample or "sign in to your account" in sample:
        raise PermissionError("SharePoint devolvió una página de autenticación.")
    if any(
        marker in sample
        for marker in (
            "/_layouts/15/",
            "wopiframe",
            "spclienttemplates",
            "suitebar",
        )
    ):
        raise ValueError("SharePoint devolvió un visor intermedio, no el HTML real.")
    if "<html" not in sample and "<!doctype html" not in sample:
        raise ValueError("El contenido recuperado no parece ser HTML.")
    content = text.encode("utf-8")
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("El HTML supera 10 MB.")
    return filename, content


def process_pending(config: Config, repository: Repository) -> int:
    reviews = repository.pending()
    if not reviews:
        return 0

    logging.info("Pendientes encontrados: %s", len(reviews))
    from playwright.sync_api import sync_playwright

    success = 0
    with sync_playwright() as playwright:
        context, page = authenticated_context(playwright, config.site_url)
        try:
            for review in reviews:
                review_id = str(review.get("id") or "")
                equipment_key = str(review.get("equipment_key") or "")
                url = str(review.get("graph_original_url") or "").strip()
                if not review_id or not equipment_key or not url:
                    logging.error("Revisión incompleta: %s", review_id or "(sin ID)")
                    continue
                try:
                    filename, content = fetch_html(page, url)
                    path = repository.upload(equipment_key, filename, content)
                    repository.mark_synced(review_id, path, filename)
                    logging.info(
                        "Sincronizado | revisión=%s | archivo=%s",
                        review_id,
                        filename,
                    )
                    success += 1
                except Exception:
                    logging.exception("Error sincronizando revisión %s", review_id)
        finally:
            context.close()
    return success


def configure_session_only() -> int:
    setup_logging()
    config = load_config()
    from playwright.sync_api import sync_playwright
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = open_context(playwright, headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(config.site_url, wait_until="domcontentloaded", timeout=90_000)
            if login_url(page.url):
                print("Complete el inicio de sesión Microsoft 365 y MFA en Edge.")
                if not wait_for_login(page, config.site_url):
                    raise RuntimeError("No se completó el inicio de sesión dentro del tiempo disponible.")
            print("Sesión Microsoft 365 configurada correctamente.")
        finally:
            context.close()
    return 0


def main() -> int:
    setup_logging()
    _lock = singleton_socket()
    config = load_config()
    repository = Repository(config)
    logging.info(
        "Agente iniciado. Versión: %s | Intervalo: %s s",
        AGENT_VERSION,
        config.poll_seconds,
    )

    while True:
        try:
            repository.heartbeat(status="active")
            process_pending(config, repository)
            repository.heartbeat(status="active")
        except Exception as exc:
            logging.exception("Error general del ciclo de sincronización")
            try:
                repository.heartbeat(
                    status="error",
                    detail=f"{type(exc).__name__}: {exc}"[:500],
                )
            except Exception:
                pass
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
