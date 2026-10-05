from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse, urlunparse

import requests

from .config import Settings
from .core import choose_html_attachment, parse_sharepoint_attachment_url


_LOGIN_MARKERS = (
    b"login.microsoftonline.com",
    b"sign in to your account",
    b'name="loginfmt"',
    b"microsoftonline",
)

_SHAREPOINT_SHELL_MARKERS = (
    b"/_layouts/15/",
    b"wopiframe",
    b"spclienttemplates",
    b"sp-pages",
    b"sharepoint page",
    b"microsoft 365",
    b"odspnext",
    b"suitebar",
)


def _canonical_attachment_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _candidate_download_urls(url: str) -> list[str]:
    value = str(url or "").strip()
    canonical = _canonical_attachment_url(value)
    candidates = [
        canonical,
        f"{canonical}?download=1",
        value,
    ]
    result: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in result:
            result.append(candidate)
    return result


def _validate_downloaded_html(
    response,
    expected_filename: str,
) -> bytes:
    final_host = urlparse(response.url).netloc.lower()
    final_path = unquote(urlparse(response.url).path).lower()
    expected_lower = str(expected_filename or "").lower()

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
    sample = content[:300_000].lower()
    if any(marker in sample for marker in _LOGIN_MARKERS):
        raise PermissionError(
            "SharePoint devolvió una página de autenticación, no el HTML del gráfico."
        )

    if b"<html" not in sample and b"<!doctype html" not in sample:
        raise ValueError(
            "La respuesta de SharePoint no contiene un documento HTML."
        )

    disposition = str(getattr(response, "headers", {}).get("Content-Disposition", "")).lower()
    disposition_matches = bool(
        expected_lower and expected_lower in unquote(disposition).lower()
    )
    path_matches = bool(expected_lower and final_path.endswith("/" + expected_lower))

    # ?web=1 puede devolver un visor/página de SharePoint que también es HTML.
    # Se rechaza expresamente ese shell para no copiarlo a Supabase como si fuera el gráfico.
    shell_detected = any(marker in sample for marker in _SHAREPOINT_SHELL_MARKERS)
    if shell_detected and not disposition_matches:
        raise ValueError(
            "SharePoint devolvió su visor web/página intermedia y no el archivo HTML real."
        )

    # Para vínculos de adjuntos, una coincidencia del nombre en ruta o Content-Disposition
    # confirma que estamos leyendo el archivo real. Si no coincide, solo se acepta cuando
    # tampoco hay señales del shell de SharePoint.
    if not path_matches and not disposition_matches and "/attachments/" not in final_path:
        raise ValueError(
            "La respuesta HTML no corresponde al adjunto solicitado."
        )

    return content


def fetch_sharepoint_html_direct(url: str) -> tuple[str, bytes]:
    """Recupera el HTML real de un adjunto SharePoint sin autenticación interactiva.

    Primero elimina ?web=1 para evitar el visor web y después prueba una variante
    de descarga. Si SharePoint exige login, el llamador puede intentar REST/API.
    """
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https" or not parsed.netloc.lower().endswith(
        ".sharepoint.com"
    ):
        raise ValueError("El vínculo debe ser HTTPS y pertenecer a *.sharepoint.com.")

    filename = Path(unquote(parsed.path)).name or "grafico_sharepoint.html"
    errors: list[str] = []

    for candidate in _candidate_download_urls(value):
        try:
            response = requests.get(
                candidate,
                headers={
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "User-Agent": "AyA-Seguimiento-Caudalimetros/1.0",
                },
                timeout=40,
                allow_redirects=True,
            )
            content = _validate_downloaded_html(response, filename)
            return filename, content
        except Exception as exc:
            errors.append(f"{candidate}: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        "No fue posible obtener el HTML real del adjunto de SharePoint. "
        + " | ".join(errors)
    )


class Microsoft365DeviceAuth:
    """Autenticación delegada: el usuario inicia sesión directamente con Microsoft."""

    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.sharepoint_user_login_configured:
            raise RuntimeError(
                "Para iniciar sesión con Microsoft 365 configure tenant_id y client_id."
            )

    def _app(self):
        try:
            import msal
        except ImportError as exc:
            raise RuntimeError("El paquete msal no está instalado.") from exc

        authority = f"https://login.microsoftonline.com/{self.settings.ms_tenant_id}"
        return msal.PublicClientApplication(
            client_id=self.settings.ms_client_id,
            authority=authority,
        )

    def scopes(self) -> list[str]:
        host = self.settings.sharepoint_site_url.split("/sites/")[0]
        return [f"{host}/AllSites.Read"]

    def initiate(self) -> dict[str, Any]:
        flow = self._app().initiate_device_flow(scopes=self.scopes())
        if "user_code" not in flow:
            raise RuntimeError(
                "Microsoft no pudo iniciar el flujo de acceso: "
                + str(flow.get("error_description") or flow.get("error") or flow)
            )
        return flow

    def complete(self, flow: dict[str, Any]) -> dict[str, Any]:
        result = self._app().acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(
                "No fue posible completar el inicio de sesión: "
                + str(
                    result.get("error_description")
                    or result.get("error")
                    or "sin detalle"
                )
            )
        return result


class DelegatedSharePointRepository:
    """SharePoint REST actuando con los permisos del usuario autenticado."""

    def __init__(self, settings: Settings, access_token: str):
        self.settings = settings
        self.access_token = str(access_token or "").strip()
        if not self.access_token:
            raise RuntimeError("No existe un token de usuario de Microsoft 365.")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
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
        if response.status_code in {401, 403}:
            raise PermissionError(
                "La sesión Microsoft 365 no tiene acceso a la lista o expiró "
                f"(HTTP {response.status_code})."
            )
        response.raise_for_status()
        rows = response.json().get("value", [])
        return sorted(rows, key=lambda x: int(x.get("Id", 0)), reverse=True)

    def list_attachments(self, item_id: int) -> list[dict[str, Any]]:
        url = (
            f"{self._list_base()}/items({int(item_id)})/AttachmentFiles"
            "?$select=FileName,ServerRelativeUrl,TimeLastModified"
        )
        response = requests.get(url, headers=self._headers(), timeout=25)
        if response.status_code in {401, 403}:
            raise PermissionError(
                "La sesión Microsoft 365 no tiene acceso a los adjuntos o expiró "
                f"(HTTP {response.status_code})."
            )
        response.raise_for_status()
        return response.json().get("value", [])

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
        if response.status_code in {401, 403}:
            raise PermissionError(
                "La sesión Microsoft 365 no tiene acceso al archivo o expiró "
                f"(HTTP {response.status_code})."
            )
        response.raise_for_status()
        return clean_filename, response.content

    def download_attachment_from_url(self, url: str) -> tuple[str, bytes]:
        parsed_link = parse_sharepoint_attachment_url(url)
        if not parsed_link:
            raise ValueError("No se pudo interpretar el vínculo de SharePoint.")
        item_id = parsed_link.get("item_id")
        filename = parsed_link.get("file_name")
        if item_id is None or not filename:
            raise ValueError(
                "El vínculo no contiene /Attachments/{id}/{archivo}."
            )
        return self.download_attachment_by_name(int(item_id), str(filename))


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

    def download_attachment_from_url(self, url: str) -> tuple[str, bytes]:
        parsed_link = parse_sharepoint_attachment_url(url)
        if not parsed_link:
            raise ValueError("No se pudo interpretar el vínculo de SharePoint.")
        item_id = parsed_link.get("item_id")
        filename = parsed_link.get("file_name")
        if item_id is None or not filename:
            raise ValueError(
                "El vínculo no contiene /Attachments/{id}/{archivo}."
            )
        return self.download_attachment_by_name(int(item_id), str(filename))

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


def retrieve_sharepoint_html(
    url: str,
    api_repository: Any | None = None,
) -> tuple[str, bytes, str]:
    """Obtiene el HTML real: acceso directo primero y REST autenticado como respaldo."""
    direct_error: Exception | None = None
    try:
        filename, content = fetch_sharepoint_html_direct(url)
        return filename, content, "direct"
    except Exception as exc:
        direct_error = exc

    if api_repository is not None:
        try:
            filename, content = api_repository.download_attachment_from_url(url)
            return filename, content, "api"
        except Exception as api_exc:
            raise RuntimeError(
                "No fue posible extraer el HTML real desde SharePoint. "
                f"Acceso directo: {direct_error}. API: {api_exc}."
            ) from api_exc

    raise RuntimeError(
        "No fue posible extraer el HTML real desde SharePoint. "
        f"Acceso directo: {direct_error}. "
        "La API REST de SharePoint no está configurada."
    )
