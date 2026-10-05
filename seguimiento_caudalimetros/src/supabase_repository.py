from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pandas as pd

from .config import Settings
from .core import safe_filename, snapshot_from_row


def _client(settings: Settings):
    if not settings.supabase_configured:
        raise RuntimeError("Supabase no está configurado.")
    try:
        from supabase import create_client
    except ImportError as exc:
        raise RuntimeError("El paquete supabase no está instalado.") from exc
    return create_client(settings.supabase_url, settings.supabase_key)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    numeric = _as_float(value)
    return int(numeric) if numeric is not None else None


class SupabaseMeterRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = _client(settings)
        self.table_name = settings.supabase_meters_table

    def load_meters(self, page_size: int = 1000) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        start = 0

        while True:
            result = (
                self.client.table(self.table_name)
                .select("*")
                .order("equipment_key")
                .range(start, start + page_size - 1)
                .execute()
            )
            batch = getattr(result, "data", None) or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
            start += page_size

        # Cada ejecución del sincronizador asigna el mismo synced_at a todo el lote.
        # Conservamos únicamente el lote más reciente para evitar que registros
        # obsoletos de sincronizaciones anteriores reaparezcan en la aplicación.
        sync_values = [
            str(item.get("synced_at") or "").strip()
            for item in rows
            if str(item.get("synced_at") or "").strip()
        ]
        if sync_values:
            latest_sync = max(sync_values)
            rows = [
                item
                for item in rows
                if str(item.get("synced_at") or "").strip() == latest_sync
            ]

        expanded: list[dict[str, Any]] = []
        for item in rows:
            attributes = dict(item.get("attributes") or {})
            key_field = str(item.get("sql_key_field") or self.settings.sql_key_field)
            attributes.setdefault(key_field, item.get("equipment_key"))

            if item.get("longitude") is not None:
                attributes["LONGITUD"] = item.get("longitude")
            if item.get("latitude") is not None:
                attributes["LATITUD"] = item.get("latitude")
            if item.get("x_crtm05") is not None:
                attributes["X_CRTM05"] = item.get("x_crtm05")
            if item.get("y_crtm05") is not None:
                attributes["Y_CRTM05"] = item.get("y_crtm05")
            if item.get("srid_original") is not None:
                attributes["SRID_ORIGINAL"] = item.get("srid_original")
            attributes["EPSG_WGS84"] = 4326
            expanded.append(attributes)

        return pd.DataFrame(expanded)

    def upsert_meters(
        self,
        meters: pd.DataFrame,
        key_column: str,
        batch_size: int = 250,
    ) -> dict[str, int]:
        payloads: list[dict[str, Any]] = []
        skipped = 0
        synced_at = datetime.now(timezone.utc).isoformat()

        for _, row in meters.iterrows():
            snapshot = snapshot_from_row(row.to_dict())
            equipment_key = snapshot.get(key_column)
            if equipment_key is None or not str(equipment_key).strip():
                skipped += 1
                continue

            payloads.append(
                {
                    "equipment_key": str(equipment_key),
                    "sql_key_field": key_column,
                    "attributes": snapshot,
                    "longitude": _as_float(snapshot.get("LONGITUD")),
                    "latitude": _as_float(snapshot.get("LATITUD")),
                    "x_crtm05": _as_float(snapshot.get("X_CRTM05")),
                    "y_crtm05": _as_float(snapshot.get("Y_CRTM05")),
                    "srid_original": _as_int(snapshot.get("SRID_ORIGINAL")),
                    "synced_at": synced_at,
                }
            )

        upserted = 0
        for start in range(0, len(payloads), batch_size):
            batch = payloads[start : start + batch_size]
            self.client.table(self.table_name).upsert(
                batch,
                on_conflict="equipment_key",
            ).execute()
            upserted += len(batch)

        deleted_stale = 0
        if payloads:
            # Solo se limpia después de completar todos los UPSERT.
            # Las revisiones históricas viven en otra tabla y no se eliminan.
            result = (
                self.client.table(self.table_name)
                .delete()
                .neq("synced_at", synced_at)
                .execute()
            )
            deleted_stale = len(getattr(result, "data", None) or [])

        return {
            "upserted": upserted,
            "skipped": skipped,
            "deleted_stale": deleted_stale,
        }

    def ping(self) -> tuple[bool, str]:
        try:
            self.client.table(self.table_name).select("equipment_key").limit(1).execute()
            return True, "Inventario de caudalímetros en Supabase accesible."
        except Exception as exc:
            return False, f"Supabase inventario: {type(exc).__name__}: {exc}"


class SupabaseReviewRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = _client(settings)
        self.table_name = settings.supabase_table
        self.bucket = settings.supabase_bucket

    def insert_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.client.table(self.table_name).insert(payload).execute()
        rows = getattr(result, "data", None) or []
        if not rows:
            raise RuntimeError("Supabase no devolvió el registro insertado.")
        return rows[0]

    def update_review(
        self,
        review_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        result = (
            self.client.table(self.table_name)
            .update(payload)
            .eq("id", str(review_id))
            .execute()
        )
        rows = getattr(result, "data", None) or []
        if not rows:
            raise RuntimeError("Supabase no devolvió el registro actualizado.")
        return rows[0]

    def delete_review(
        self,
        review_id: str,
        graph_storage_path: str | None = None,
    ) -> dict[str, Any]:
        result = (
            self.client.table(self.table_name)
            .delete()
            .eq("id", str(review_id))
            .execute()
        )
        storage_warning = None
        if graph_storage_path:
            try:
                self.delete_html(str(graph_storage_path))
            except Exception as exc:
                storage_warning = (
                    "El registro fue eliminado, pero no se pudo limpiar el archivo gráfico "
                    f"del almacenamiento: {exc}"
                )
        rows = getattr(result, "data", None) or []
        return {
            "deleted": bool(rows) or result is not None,
            "storage_warning": storage_warning,
        }

    def list_reviews(
        self,
        equipment_key: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = self.client.table(self.table_name).select("*")
        if equipment_key:
            query = query.eq("equipment_key", str(equipment_key))
        result = query.order("reviewed_at", desc=True).limit(limit).execute()
        return getattr(result, "data", None) or []

    def latest_review(self, equipment_key: str) -> dict[str, Any] | None:
        rows = self.list_reviews(equipment_key=equipment_key, limit=1)
        return rows[0] if rows else None

    def list_dashboard_reviews(self, page_size: int = 500) -> list[dict[str, Any]]:
        """Read the complete history without the normal per-equipment limit."""
        if page_size < 1:
            raise ValueError("page_size debe ser positivo.")
        rows: list[dict[str, Any]] = []
        while True:
            result = (
                self.client.table(self.table_name)
                .select("*")
                .order("reviewed_at", desc=True)
                .order("id", desc=True)
                .range(len(rows), len(rows) + page_size - 1)
                .execute()
            )
            page = getattr(result, "data", None) or []
            rows.extend(page)
            # Continue until empty: a server may cap pages below page_size.
            if not page:
                return rows

    def list_sharepoint_link_reviews(
        self,
        pending_only: bool = True,
        item_id: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        query = (
            self.client.table(self.table_name)
            .select("*")
            .eq("graph_source", "sharepoint_link")
            .not_.is_("graph_original_url", "null")
        )
        if pending_only:
            query = query.is_("graph_storage_path", "null")
        if item_id is not None:
            query = query.eq("sharepoint_item_id", int(item_id))
        result = query.order("reviewed_at", desc=False).limit(limit).execute()
        return getattr(result, "data", None) or []

    def update_review_graph_cache(
        self,
        review_id: str,
        graph_storage_path: str,
        sharepoint_file_name: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "graph_storage_path": graph_storage_path,
        }
        if sharepoint_file_name:
            payload["sharepoint_file_name"] = sharepoint_file_name

        result = (
            self.client.table(self.table_name)
            .update(payload)
            .eq("id", str(review_id))
            .execute()
        )
        rows = getattr(result, "data", None) or []
        return rows[0] if rows else payload


    def mark_review_graph_pending(self, review_id: str) -> dict[str, Any]:
        current = (
            self.client.table(self.table_name)
            .select("graph_storage_path")
            .eq("id", str(review_id))
            .limit(1)
            .execute()
        )
        current_rows = getattr(current, "data", None) or []
        old_path = (
            str(current_rows[0].get("graph_storage_path") or "").strip()
            if current_rows
            else ""
        )

        result = (
            self.client.table(self.table_name)
            .update(
                {
                    "graph_storage_path": None,
                    "graph_format": "html",
                }
            )
            .eq("id", str(review_id))
            .execute()
        )

        if old_path:
            try:
                self.delete_html(old_path)
            except Exception:
                pass

        rows = getattr(result, "data", None) or []
        return (
            rows[0]
            if rows
            else {
                "graph_storage_path": None,
                "graph_format": "html",
            }
        )

    def upload_html(self, equipment_key: str, filename: str, content: bytes) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = (
            f"{safe_filename(str(equipment_key))}/"
            f"{timestamp}_{uuid4().hex[:8]}_{safe_filename(filename)}"
        )
        self.client.storage.from_(self.bucket).upload(
            path=path,
            file=content,
            file_options={
                "content-type": "text/html; charset=utf-8",
                "upsert": "false",
            },
        )
        return path

    def download_html(self, path: str) -> bytes:
        content = self.client.storage.from_(self.bucket).download(path)
        if isinstance(content, bytes):
            return content
        if hasattr(content, "read"):
            return content.read()
        return bytes(content)

    def delete_html(self, path: str) -> None:
        if not str(path or "").strip():
            return
        self.client.storage.from_(self.bucket).remove([str(path)])

    def agent_heartbeats(
        self,
        active_within_seconds: int = 180,
    ) -> list[dict[str, Any]]:
        try:
            entries = self.client.storage.from_(self.bucket).list("agent_status")
        except Exception:
            return []

        now = datetime.now(timezone.utc)
        heartbeats: list[dict[str, Any]] = []

        for entry in entries or []:
            if isinstance(entry, dict):
                name = str(entry.get("name") or "")
            else:
                name = str(getattr(entry, "name", "") or "")

            if not name.endswith(".json"):
                continue

            path = f"agent_status/{name}"
            try:
                raw = self.client.storage.from_(self.bucket).download(path)
                if hasattr(raw, "read"):
                    raw = raw.read()
                if not isinstance(raw, bytes):
                    raw = bytes(raw)
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                continue

            last_seen_text = str(payload.get("last_seen_utc") or "").strip()
            age_seconds = None
            active = False
            if last_seen_text:
                try:
                    last_seen = datetime.fromisoformat(
                        last_seen_text.replace("Z", "+00:00")
                    )
                    if last_seen.tzinfo is None:
                        last_seen = last_seen.replace(tzinfo=timezone.utc)
                    age_seconds = max(
                        0,
                        int((now - last_seen.astimezone(timezone.utc)).total_seconds()),
                    )
                    active = age_seconds <= int(active_within_seconds)
                except ValueError:
                    pass

            payload["storage_path"] = path
            payload["age_seconds"] = age_seconds
            payload["active"] = active
            heartbeats.append(payload)

        heartbeats.sort(
            key=lambda item: (
                item.get("age_seconds") is None,
                item.get("age_seconds")
                if item.get("age_seconds") is not None
                else 10**12,
            )
        )
        return heartbeats

    def ping(self) -> tuple[bool, str]:
        try:
            self.client.table(self.table_name).select("id").limit(1).execute()
            return True, "Tabla de revisiones en Supabase accesible."
        except Exception as exc:
            return False, f"Supabase revisiones: {type(exc).__name__}: {exc}"
