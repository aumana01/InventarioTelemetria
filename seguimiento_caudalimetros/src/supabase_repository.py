from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .config import Settings
from .core import safe_filename


class SupabaseReviewRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.supabase_configured:
            raise RuntimeError("Supabase no está configurado.")
        try:
            from supabase import create_client
        except ImportError as exc:
            raise RuntimeError("El paquete supabase no está instalado.") from exc
        self.client = create_client(settings.supabase_url, settings.supabase_key)
        self.table_name = settings.supabase_table
        self.bucket = settings.supabase_bucket

    def insert_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.client.table(self.table_name).insert(payload).execute()
        rows = getattr(result, "data", None) or []
        if not rows:
            raise RuntimeError("Supabase no devolvió el registro insertado.")
        return rows[0]

    def list_reviews(self, equipment_key: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        query = self.client.table(self.table_name).select("*")
        if equipment_key:
            query = query.eq("equipment_key", str(equipment_key))
        result = query.order("reviewed_at", desc=True).limit(limit).execute()
        return getattr(result, "data", None) or []

    def latest_review(self, equipment_key: str) -> dict[str, Any] | None:
        rows = self.list_reviews(equipment_key=equipment_key, limit=1)
        return rows[0] if rows else None

    def upload_html(self, equipment_key: str, filename: str, content: bytes) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = f"{safe_filename(str(equipment_key))}/{timestamp}_{uuid4().hex[:8]}_{safe_filename(filename)}"
        self.client.storage.from_(self.bucket).upload(
            path=path,
            file=content,
            file_options={"content-type": "text/html; charset=utf-8", "upsert": "false"},
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
            return True, "Conexión Supabase correcta."
        except Exception as exc:
            return False, f"Supabase: {type(exc).__name__}: {exc}"
