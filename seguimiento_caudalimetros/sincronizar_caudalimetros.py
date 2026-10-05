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
        print("La consulta SQL no devolvió caudalímetros con geometría. No se sincronizó nada.")
        return 0

    key_column = determine_key_column_from_frame(meters, settings.sql_key_field)
    print(f"Registros leídos: {len(meters)}")
    print(f"Clave utilizada: {key_column}")
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
    print(
        "Nota: la sincronización usa UPSERT y no elimina registros de Supabase "
        "que hayan desaparecido de SQL."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
