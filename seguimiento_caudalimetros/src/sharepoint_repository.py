from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

from .config import Settings
from .core import choose_html_attachment


def fetch_sharepoint_html_direct(url: str) -> tuple[str, bytes]:
    """Intenta recuperar un HTML directamente desde un vínculo *.sharepoint.com.

    Esto solo funciona cuando SharePoint permite al servidor de Streamlit acceder al
    adjunto sin una sesión interactiva. Si el sitio redirige al login de Microsoft,
    se informa como acceso autenticado requerido para que el llamador pruebe la API.
    """
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https" or not parsed.netloc.lower().endswith(
        ".sharepoint.com"
    ):
        raise ValueError("El vínculo debe ser HTTPS y pertenecer a *.sharepoint.com.")

    response = requests.get(
        value,
        headers={
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "User-Agent": "AyA-Seguimiento-Caudalimetros/1.0",
        },
        timeout=40,
        allow_redirects=True,
    )

    final_host = urlparse(response.url).netloc.lower()
    if "login.microsoftonline.com" in final_host or "login.microsoft.com" in final_host:
        raise PermissionError(
            "SharePoint redirigió al inicio de sesión de Microsoft; se requiere acceso autenticado."
        )

    if response.status_code in {401, 403}:
        raise PermissionError(
            f"SharePoint requiere autenticación (HTTP {response.status_code})."
        )

    response.raise_for_status()

    content = response.content
    sample = content[:200_000].lower()
    login_markers = (
        b"login.microsoftonline.com",
        b"sign in to your account",
        b"name=\"loginfmt\"",
        b"microsoftonline",
    )
    if any(marker in sample for marker in login_markers):
        raise PermissionError(
            "El vínculo devolvió una página de autenticación de Microsoft, no el HTML del gráfico."
        )

    if b"<html" not in sample and b"<!doctype html" not in sample:
        raise ValueError(
            "El vínculo respondió, pero el contenido recuperado no parece ser un archivo HTML."
        )

    filename = Path(unquote(parsed.path)).name or "grafico_sharepoint.html"
    return filename, content


class SharePointListRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.sharepoint_configured:
            raise RuntimeError("Microsoft List / SharePoint no está configurado.")

    def _token(self) -> str:
        try:
            import msal
        except ImportError as exc:
            raise RuntimeError("El paquete msal no está instalado.") from exc

        authority = f"https://login.microsoftonline.com/{self.settings.ms_tenant_id}"
        host = self.settings.sharepoint_site_url.split("/sites/")[0]
        app = msal.ConfidentialClientApplication(
            client_id=self.settings.ms_client_id,
            client_credential=self.settings.ms_client_secret,
            authority=authority,
        )
        result = app.acquire_token_for_client(scopes=[f"{host}/.default"])
        token = result.get("access_token")
        if not token:
            raise RuntimeError(
                "No fue posible obtener token de SharePoint: "
                + str(result.get("error_description") or result.get("error") or "sin detalle")
            )
        return token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/json;odata=nometadata",
        }

    def _list_base(self) -> str:
        title = self.settings.sharepoint_list_title.replace("'", "''")
        return (
            f"{self.settings.sharepoint_site_url}/_api/web/lists/"
            f"getbytitle('{title}')"
        )

    def list_items(self, limit: int = 5000) -> list[dict[str, Any]]:
        url = f"{self._list_base()}/items?$select=Id,Title&$top={int(limit)}"
        response = requests.get(url, headers=self._headers(), timeout=25)
        response.raise_for_status()
        rows = response.json().get("value", [])
        return sorted(rows, key=lambda x: int(x.get("Id", 0)), reverse=True)

    def list_attachments(self, item_id: int) -> list[dict[str, Any]]:
        url = (
            f"{self._list_base()}/items({int(item_id)})/AttachmentFiles"
            "?$select=FileName,ServerRelativeUrl,TimeLastModified"
        )
        response = requests.get(url, headers=self._headers(), timeout=25)
        response.raise_for_status()
        return response.json().get("value", [])

    def download_attachment_by_name(
        self,
        item_id: int,
        filename: str,
    ) -> tuple[str, bytes]:
        clean_filename = str(filename or "").strip()
        if not clean_filename:
            raise ValueError("No se indicó el nombre del adjunto de SharePoint.")
        escaped = clean_filename.replace("'", "''")
        url = (
            f"{self._list_base()}/items({int(item_id)})/"
            f"AttachmentFiles('{escaped}')/$value"
        )
        response = requests.get(url, headers=self._headers(), timeout=40)
        response.raise_for_status()
        return clean_filename, response.content

    def download_html_attachment(self, item_id: int) -> tuple[str, bytes]:
        attachments = self.list_attachments(item_id)
        selected = choose_html_attachment(attachments)
        if not selected:
            raise FileNotFoundError(
                f"El ID {item_id} no contiene adjuntos .html/.htm en Microsoft List."
            )
        return self.download_attachment_by_name(
            int(item_id),
            str(selected["FileName"]),
        )

    def ping(self) -> tuple[bool, str]:
        try:
            rows = self.list_items(limit=1)
            return True, f"Microsoft List accesible ({len(rows)} registro de prueba)."
        except Exception as exc:
            return False, f"SharePoint: {type(exc).__name__}: {exc}"
