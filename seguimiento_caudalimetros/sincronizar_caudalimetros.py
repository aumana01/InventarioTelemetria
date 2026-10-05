from __future__ import annotations

import sys

from src.config import Settings
from src.core import determine_key_column_from_frame
from src.sql_repository import SqlMeterRepository
from src.supabase_repository import SupabaseMeterRepository


def main() -> int:
    settings = Settings.load()

    if not settings.sql_configured:
        print(
            "ERROR: faltan credenciales SQL. Configure .streamlit/secrets.toml "
            "o las variables SQL_SERVER, SQL_DATABASE, SQL_USERNAME y SQL_PASSWORD."
        )
        return 2

    if not settings.supabase_configured:
        print(
            "ERROR: falta Supabase. Configure SUPABASE_URL y "
            "SUPABASE_SERVICE_ROLE_KEY o la sección [supabase] de secrets.toml."
        )
        return 2

    print(
        f"Leyendo {settings.sql_schema}.{settings.sql_table} "
        f"desde {settings.sql_server}..."
    )
    meters = SqlMeterRepository(settings).load_meters()

    if meters.empty:
        print("La consulta SQL no devolvió registros. No se sincronizó nada.")
        return 0

    total = len(meters)
    has_shape = (
        meters["SRID_ORIGINAL"].notna()
        if "SRID_ORIGINAL" in meters.columns
        else None
    )
    valid_coordinates = (
        meters["X_CRTM05"].notna() & meters["Y_CRTM05"].notna()
        if {"X_CRTM05", "Y_CRTM05"}.issubset(meters.columns)
        else None
    )

    print("=== DIAGNÓSTICO DE INVENTARIO SQL ===")
    print(f"Registros totales: {total}")
    if has_shape is not None:
        print(f"Con geometría: {int(has_shape.sum())}")
        print(f"Sin geometría: {int((~has_shape).sum())}")
    if valid_coordinates is not None:
        print(f"Con coordenadas X/Y válidas: {int(valid_coordinates.sum())}")
        print(f"Sin coordenadas X/Y válidas: {int((~valid_coordinates).sum())}")

    key_column = determine_key_column_from_frame(meters, settings.sql_key_field)
    key_text = meters[key_column].astype("string").str.strip()
    key_valid = key_text.notna() & ~key_text.isin(["", "nan", "none", "null"])
    duplicate_count = int(key_text[key_valid].duplicated(keep=False).sum())

    print(f"Clave utilizada: {key_column}")
    print(f"Claves utilizables: {int(key_valid.sum())}")
    print(f"Filas con clave duplicada: {duplicate_count}")
    print(
        f"Sincronizando en Supabase -> public.{settings.supabase_meters_table}..."
    )

    result = SupabaseMeterRepository(settings).upsert_meters(
        meters=meters,
        key_column=key_column,
    )

    print(
        "Sincronización completada. "
        f"Actualizados/insertados: {result['upserted']}; "
        f"omitidos por clave vacía: {result['skipped']}."
    )

    try:
        supabase_total = len(SupabaseMeterRepository(settings).load_meters())
        print(f"Registros disponibles en Supabase después de sincronizar: {supabase_total}")
        if supabase_total != total - result["skipped"]:
            print(
                "ADVERTENCIA: el total de Supabase no coincide con el inventario SQL "
                "sin claves vacías. Puede haber registros históricos con otra clave "
                "o registros duplicados en la fuente."
            )
    except Exception as exc:
        print(f"ADVERTENCIA: no fue posible verificar el total final en Supabase: {exc}")

    print(
        "Nota: la sincronización usa UPSERT y no elimina registros de Supabase "
        "que hayan desaparecido de SQL."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
