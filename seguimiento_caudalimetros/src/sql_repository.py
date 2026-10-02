from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pandas as pd
from pyproj import Transformer

from .config import Settings

if TYPE_CHECKING:
    import pyodbc


def _quote_identifier(value: str) -> str:
    if not value or not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError(f"Identificador SQL no permitido: {value!r}")
    return f"[{value}]"


def transform_crtm05_to_wgs84(meters: pd.DataFrame) -> pd.DataFrame:
    """Transforma X/Y CRTM05 (EPSG:5367) a LONGITUD/LATITUD WGS84 (EPSG:4326)."""
    if meters.empty:
        return meters.copy()
    required = {"X_CRTM05", "Y_CRTM05"}
    missing = required.difference(meters.columns)
    if missing:
        raise ValueError(f"Faltan columnas de coordenadas: {sorted(missing)}")
    clean = meters.dropna(subset=["X_CRTM05", "Y_CRTM05"]).copy()
    transformer = Transformer.from_crs("EPSG:5367", "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(
        clean["X_CRTM05"].astype(float).tolist(),
        clean["Y_CRTM05"].astype(float).tolist(),
    )
    clean["LONGITUD"] = lon
    clean["LATITUD"] = lat
    clean["EPSG_WGS84"] = 4326
    return clean


class SqlMeterRepository:
    def __init__(self, settings: Settings):
        self.settings = settings

    def connect(self) -> "pyodbc.Connection":
        try:
            import pyodbc
        except ImportError as exc:
            raise RuntimeError("pyodbc no está instalado.") from exc

        s = self.settings
        if not s.sql_configured:
            raise RuntimeError("La conexión SQL no está configurada.")
        connection_string = (
            f"DRIVER={{{s.sql_driver}}};"
            f"SERVER={s.sql_server};"
            f"DATABASE={s.sql_database};"
            f"UID={s.sql_username};"
            f"PWD={s.sql_password};"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=15;"
        )
        return pyodbc.connect(connection_string)

    def load_meters(self) -> pd.DataFrame:
        schema = self.settings.sql_schema
        table = self.settings.sql_table
        schema_q = _quote_identifier(schema)
        table_q = _quote_identifier(table)

        with self.connect() as conn:
            sql_fields = """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ?
                  AND TABLE_NAME = ?
                  AND UPPER(COLUMN_NAME) <> 'SHAPE'
                ORDER BY ORDINAL_POSITION
            """
            fields = pd.read_sql_query(sql_fields, conn, params=[schema, table])
            if fields.empty:
                raise RuntimeError(
                    f"No se encontraron columnas para {schema}.{table}. Verifique permisos y nombre."
                )

            field_names = fields["COLUMN_NAME"].astype(str).tolist()
            columns_sql = ",\n    ".join(
                "[" + name.replace("]", "]]") + "]" for name in field_names
            )
            query = f"""
                SELECT
                    {columns_sql},
                    SHAPE.STX AS X_CRTM05,
                    SHAPE.STY AS Y_CRTM05,
                    SHAPE.STSrid AS SRID_ORIGINAL
                FROM {schema_q}.{table_q}
                WHERE SHAPE IS NOT NULL
            """
            meters = pd.read_sql_query(query, conn)

        return transform_crtm05_to_wgs84(meters)

    def ping(self) -> tuple[bool, str]:
        try:
            with self.connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return True, "Conexión SQL correcta."
        except Exception as exc:
            return False, f"SQL: {type(exc).__name__}: {exc}"
