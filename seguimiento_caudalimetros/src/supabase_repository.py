from __future__ import annotations

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

        return {"upserted": upserted, "skipped": skipped}

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
        result = (
            self.client.table(self.table_name)
            .update({"graph_storage_path": None})
            .eq("id", str(review_id))
            .execute()
        )
        rows = getattr(result, "data", None) or []
        return rows[0] if rows else {"graph_storage_path": None}

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

    def ping(self) -> tuple[bool, str]:
        try:
            self.client.table(self.table_name).select("id").limit(1).execute()
            return True, "Tabla de revisiones en Supabase accesible."
        except Exception as exc:
            return False, f"Supabase revisiones: {type(exc).__name__}: {exc}"
