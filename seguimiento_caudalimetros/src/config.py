from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _secret(section: str, key: str, env_name: str, default: Any = None) -> Any:
    if env_name in os.environ:
        return os.environ[env_name]
    try:
        import streamlit as st

        sec = st.secrets.get(section, {})
        if key in sec:
            return sec[key]
    except Exception:
        pass
    return default


def _data_source(value: Any) -> str:
    source = str(value or "supabase").strip().lower()
    if source not in {"supabase", "sql", "auto"}:
        raise ValueError(
            "app.data_source debe ser 'supabase', 'sql' o 'auto'."
        )
    return source


@dataclass(frozen=True)
class Settings:
    sql_server: str
    sql_database: str
    sql_username: str
    sql_password: str
    sql_driver: str
    sql_schema: str
    sql_table: str
    sql_key_field: str

    supabase_url: str
    supabase_key: str
    supabase_table: str
    supabase_meters_table: str
    supabase_bucket: str

    sharepoint_site_url: str
    sharepoint_list_title: str
    ms_tenant_id: str
    ms_client_id: str
    ms_client_secret: str

    demo_mode: bool
    data_source: str
    app_password: str

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            sql_server=str(_secret("sql", "server", "SQL_SERVER", "")),
            sql_database=str(_secret("sql", "database", "SQL_DATABASE", "GIS_RME")),
            sql_username=str(_secret("sql", "username", "SQL_USERNAME", "")),
            sql_password=str(_secret("sql", "password", "SQL_PASSWORD", "")),
            sql_driver=str(
                _secret("sql", "driver", "SQL_DRIVER", "ODBC Driver 13 for SQL Server")
            ),
            sql_schema=str(_secret("sql", "schema", "SQL_SCHEMA", "AYA")),
            sql_table=str(
                _secret("sql", "table", "SQL_TABLE", "MSG_Medidores_de_Caudal")
            ),
            sql_key_field=str(
                _secret("sql", "key_field", "SQL_KEY_FIELD", "Código_Caudalimetro")
            ),
            supabase_url=str(_secret("supabase", "url", "SUPABASE_URL", "")),
            supabase_key=str(
                _secret("supabase", "service_role_key", "SUPABASE_SERVICE_ROLE_KEY", "")
            ),
            supabase_table=str(
                _secret("supabase", "table", "SUPABASE_TABLE", "caudalimetro_revisiones")
            ),
            supabase_meters_table=str(
                _secret(
                    "supabase",
                    "meters_table",
                    "SUPABASE_METERS_TABLE",
                    "caudalimetros",
                )
            ),
            supabase_bucket=str(
                _secret("supabase", "bucket", "SUPABASE_BUCKET", "caudalimetros-graficos")
            ),
            sharepoint_site_url=str(
                _secret(
                    "sharepoint",
                    "site_url",
                    "SHAREPOINT_SITE_URL",
                    "https://intranetaya.sharepoint.com/sites/MejoramientodeSistemas769",
                )
            ).rstrip("/"),
            sharepoint_list_title=str(
                _secret(
                    "sharepoint",
                    "list_title",
                    "SHAREPOINT_LIST_TITLE",
                    "Seguimiento de Detección de Fugas GAM",
                )
            ),
            ms_tenant_id=str(_secret("sharepoint", "tenant_id", "MS_TENANT_ID", "")),
            ms_client_id=str(_secret("sharepoint", "client_id", "MS_CLIENT_ID", "")),
            ms_client_secret=str(
                _secret("sharepoint", "client_secret", "MS_CLIENT_SECRET", "")
            ),
            demo_mode=_as_bool(
                _secret("app", "demo_mode", "APP_DEMO_MODE", "false"), default=False
            ),
            data_source=_data_source(
                _secret("app", "data_source", "APP_DATA_SOURCE", "supabase")
            ),
            app_password=str(_secret("app", "password", "APP_PASSWORD", "")),
        )

    @property
    def sql_configured(self) -> bool:
        return all([self.sql_server, self.sql_database, self.sql_username, self.sql_password])

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def meter_data_source(self) -> str:
        if self.data_source == "auto":
            if self.supabase_configured:
                return "supabase"
            return "sql"
        return self.data_source

    @property
    def sharepoint_configured(self) -> bool:
        return all(
            [
                self.sharepoint_site_url,
                self.sharepoint_list_title,
                self.ms_tenant_id,
                self.ms_client_id,
                self.ms_client_secret,
            ]
        )


    @property
    def sharepoint_user_login_configured(self) -> bool:
        """Login delegado de usuario: no requiere client_secret."""
        return all(
            [
                self.sharepoint_site_url,
                self.sharepoint_list_title,
                self.ms_tenant_id,
                self.ms_client_id,
            ]
        )
