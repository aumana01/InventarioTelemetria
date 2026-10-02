from __future__ import annotations

from typing import Any

import requests

from .config import Settings
from .core import choose_html_attachment


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

    def download_html_attachment(self, item_id: int) -> tuple[str, bytes]:
        attachments = self.list_attachments(item_id)
        selected = choose_html_attachment(attachments)
        if not selected:
            raise FileNotFoundError(
                f"El ID {item_id} no contiene adjuntos .html/.htm en Microsoft List."
            )
        filename = selected["FileName"]
        escaped = str(filename).replace("'", "''")
        url = (
            f"{self._list_base()}/items({int(item_id)})/"
            f"AttachmentFiles('{escaped}')/$value"
        )
        response = requests.get(url, headers=self._headers(), timeout=40)
        response.raise_for_status()
        return str(filename), response.content

    def ping(self) -> tuple[bool, str]:
        try:
            rows = self.list_items(limit=1)
            return True, f"Microsoft List accesible ({len(rows)} registro de prueba)."
        except Exception as exc:
            return False, f"SharePoint: {type(exc).__name__}: {exc}"
