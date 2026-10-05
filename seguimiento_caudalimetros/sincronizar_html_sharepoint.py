from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse

from src.config import Settings
from src.core import parse_sharepoint_attachment_url, validate_html_file
from src.supabase_repository import SupabaseReviewRepository


def browser_profile_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / "AyA" / "SeguimientoCaudalimetros" / "edge_profile"
    return Path.home() / ".aya_seguimiento_caudalimetros" / "edge_profile"


def canonical_attachment_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def is_microsoft_login_url(url: str) -> bool:
    host = urlparse(str(url or "")).netloc.lower()
    return (
        "login.microsoftonline.com" in host
        or "login.microsoft.com" in host
        or "login.live.com" in host
    )


def ensure_sharepoint_session(page, site_url: str, interactive: bool = True) -> None:
    print("Abriendo SharePoint en Microsoft Edge...")
    page.goto(site_url, wait_until="domcontentloaded", timeout=90_000)

    if is_microsoft_login_url(page.url) and interactive:
        print()
        print("Microsoft 365 solicita autenticación.")
        print("Complete el inicio de sesión y MFA directamente en la ventana de Edge.")
        input("Cuando pueda ver SharePoint, vuelva a esta ventana y presione ENTER... ")
        page.goto(site_url, wait_until="domcontentloaded", timeout=90_000)

    if is_microsoft_login_url(page.url):
        raise RuntimeError(
            "La sesión de Microsoft 365 no quedó autenticada. "
            "Complete el inicio de sesión en Edge y vuelva a ejecutar el sincronizador."
        )

    print("Sesión de SharePoint disponible.")


def fetch_attachment_html(page, url: str) -> tuple[str, bytes]:
    parsed_link = parse_sharepoint_attachment_url(url)
    if not parsed_link:
        raise ValueError("El vínculo guardado no corresponde a un adjunto SharePoint válido.")

    filename = str(parsed_link.get("file_name") or "").strip()
    if not filename:
        filename = Path(unquote(urlparse(url).path)).name or "grafico_sharepoint.html"

    target = canonical_attachment_url(url)

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
                finalUrl: response.url,
                contentType: response.headers.get("content-type") || "",
                disposition: response.headers.get("content-disposition") || "",
                text
            };
        }""",
        target,
    )

    status = int(result.get("status") or 0)
    if status in {401, 403}:
        raise PermissionError(
            f"SharePoint rechazó la sesión del navegador (HTTP {status}). "
            "Abra nuevamente Edge y verifique que la cuenta tenga acceso al archivo."
        )
    if not result.get("ok"):
        raise RuntimeError(f"SharePoint respondió HTTP {status} al descargar el adjunto.")

    html_text = str(result.get("text") or "")
    sample = html_text[:300_000].lower()
    if "login.microsoftonline.com" in sample or "sign in to your account" in sample:
        raise PermissionError(
            "SharePoint devolvió una página de inicio de sesión en lugar del archivo HTML."
        )

    sharepoint_shell_markers = (
        "/_layouts/15/",
        "wopiframe",
        "spclienttemplates",
        "sharepoint page",
        "suitebar",
    )
    if any(marker in sample for marker in sharepoint_shell_markers):
        raise ValueError(
            "SharePoint devolvió una página/visor intermedio y no el HTML real del gráfico."
        )

    content = html_text.encode("utf-8")
    validation = validate_html_file(filename, content)
    if not validation.ok:
        raise ValueError("; ".join(validation.errors))

    return filename, content


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sincroniza los HTML asociados a vínculos de Microsoft List/SharePoint "
            "usando una sesión local de Microsoft Edge."
        )
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Vuelve a extraer también revisiones que ya tienen HTML en Supabase.",
    )
    parser.add_argument(
        "--item-id",
        type=int,
        default=None,
        help="Procesa únicamente el ID de Microsoft List indicado, por ejemplo 2013.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.load()

    if not settings.supabase_configured:
        print(
            "ERROR: Supabase no está configurado. Revise .streamlit/secrets.toml "
            "con SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY."
        )
        return 2

    review_repo = SupabaseReviewRepository(settings)
    pending_only = not args.refresh and args.item_id is None
    reviews = review_repo.list_sharepoint_link_reviews(
        pending_only=pending_only,
        item_id=args.item_id,
    )

    if not reviews:
        if args.item_id is not None:
            print(f"No se encontraron revisiones SharePoint para item ID {args.item_id}.")
        elif args.refresh:
            print("No se encontraron revisiones con vínculo SharePoint.")
        else:
            print("No hay HTML de SharePoint pendientes de sincronización.")
        return 0

    print(f"Revisiones a procesar: {len(reviews)}")
    if args.refresh:
        print("Modo REFRESH: se reemplazará la referencia de caché por una copia nueva.")
    if args.item_id is not None:
        print(f"Filtro Microsoft List item ID: {args.item_id}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "ERROR: falta Playwright. Ejecute: python -m pip install -r requirements.txt"
        )
        return 2

    profile = browser_profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    print(f"Perfil local de Edge: {profile}")

    success = 0
    failed = 0

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            channel="msedge",
            headless=False,
            accept_downloads=True,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            ensure_sharepoint_session(page, settings.sharepoint_site_url)

            for index, review in enumerate(reviews, start=1):
                review_id = str(review.get("id") or "")
                equipment_key = str(review.get("equipment_key") or "")
                original_url = str(review.get("graph_original_url") or "").strip()
                item_id = review.get("sharepoint_item_id")

                print()
                print(
                    f"[{index}/{len(reviews)}] Equipo {equipment_key} | "
                    f"List ID {item_id or 'sin ID'}"
                )

                if not review_id or not equipment_key or not original_url:
                    print("  OMITIDO: revisión incompleta.")
                    failed += 1
                    continue

                try:
                    filename, content = fetch_attachment_html(page, original_url)
                    new_path = review_repo.upload_html(
                        equipment_key=equipment_key,
                        filename=filename,
                        content=content,
                    )
                    review_repo.update_review_graph_cache(
                        review_id=review_id,
                        graph_storage_path=new_path,
                        sharepoint_file_name=filename,
                    )
                    print(f"  OK: {filename}")
                    print(f"  Supabase: {new_path}")
                    success += 1
                except Exception as exc:
                    print(f"  ERROR: {type(exc).__name__}: {exc}")
                    failed += 1
        finally:
            context.close()

    print()
    print("=" * 72)
    print(f"Sincronizados correctamente: {success}")
    print(f"Con error: {failed}")
    print("=" * 72)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
