from types import SimpleNamespace

import src.supabase_repository as repository_module
from src.supabase_repository import SupabaseMeterRepository, SupabaseReviewRepository


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.start = 0
        self.end = 999

    def select(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self.start = start
        self.end = end
        return self

    def execute(self):
        return FakeResponse(self.rows[self.start : self.end + 1])


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return FakeQuery(self.rows)


def test_load_meters_reconstructs_dataframe(monkeypatch):
    rows = [
        {
            "equipment_key": "FM-001",
            "sql_key_field": "Código_Caudalimetro",
            "attributes": {
                "Código_Caudalimetro": "FM-001",
                "Nombre": "Medidor prueba",
            },
            "longitude": -84.1,
            "latitude": 9.9,
            "x_crtm05": 490000.0,
            "y_crtm05": 1097000.0,
            "srid_original": 5367,
        }
    ]
    settings = SimpleNamespace(
        supabase_configured=True,
        supabase_url="https://example.supabase.co",
        supabase_key="secret",
        supabase_meters_table="caudalimetros",
        sql_key_field="Código_Caudalimetro",
    )
    monkeypatch.setattr(repository_module, "_client", lambda _settings: FakeClient(rows))

    result = SupabaseMeterRepository(settings).load_meters()

    assert len(result) == 1
    assert result.iloc[0]["Código_Caudalimetro"] == "FM-001"
    assert result.iloc[0]["Nombre"] == "Medidor prueba"
    assert float(result.iloc[0]["LONGITUD"]) == -84.1
    assert float(result.iloc[0]["LATITUD"]) == 9.9
    assert int(result.iloc[0]["EPSG_WGS84"]) == 4326


def test_load_meters_uses_only_latest_sync_batch(monkeypatch):
    rows = [
        {
            "equipment_key": "OLD-001",
            "sql_key_field": "OBJECTID",
            "attributes": {"OBJECTID": 1, "Nombre": "Registro antiguo"},
            "longitude": -84.1,
            "latitude": 9.9,
            "x_crtm05": 490000.0,
            "y_crtm05": 1097000.0,
            "srid_original": 5367,
            "synced_at": "2026-10-05T20:00:00+00:00",
        },
        {
            "equipment_key": "NEW-001",
            "sql_key_field": "OBJECTID",
            "attributes": {"OBJECTID": 2, "Nombre": "Registro vigente"},
            "longitude": -84.2,
            "latitude": 9.8,
            "x_crtm05": 491000.0,
            "y_crtm05": 1098000.0,
            "srid_original": 5367,
            "synced_at": "2026-10-05T22:00:00+00:00",
        },
    ]
    settings = SimpleNamespace(
        supabase_configured=True,
        supabase_url="https://example.supabase.co",
        supabase_key="secret",
        supabase_meters_table="caudalimetros",
        sql_key_field="OBJECTID",
    )
    monkeypatch.setattr(repository_module, "_client", lambda _settings: FakeClient(rows))

    result = SupabaseMeterRepository(settings).load_meters()

    assert len(result) == 1
    assert int(result.iloc[0]["OBJECTID"]) == 2
    assert result.iloc[0]["Nombre"] == "Registro vigente"


def test_equipment_control_defaults_are_scoped_and_persist_across_blank_revisions():
    rows = [
        {"equipment_key": "A", "reviewed_at": "2026-10-09T12:00:00Z",
         "equipment_type": "Ultrasónico", "equipment_serial": None, "transducer_serial": None},
        {"equipment_key": "B", "reviewed_at": "2026-10-08T12:00:00Z",
         "equipment_type": "Ultrasónico", "equipment_serial": "OTRO", "transducer_serial": "OTRO-T"},
        {"equipment_key": "A", "reviewed_at": "2026-10-07T12:00:00Z",
         "equipment_type": "Ultrasónico", "equipment_serial": "EQ-A", "transducer_serial": "TR-A"},
    ]

    class ControlQuery:
        def __init__(self):
            self.equipment = None
            self.start = 0
            self.end = 100

        def select(self, *_args):
            return self

        def eq(self, field, value):
            assert field == "equipment_key"
            self.equipment = value
            return self

        def order(self, field, desc=False):
            assert field == "reviewed_at" and desc
            return self

        def range(self, start, end):
            self.start, self.end = start, end
            return self

        def execute(self):
            subset = sorted(
                (r for r in rows if r["equipment_key"] == self.equipment),
                key=lambda r: r["reviewed_at"], reverse=True,
            )
            return FakeResponse(subset[self.start:self.end + 1])

    repo = object.__new__(SupabaseReviewRepository)
    repo.table_name = "caudalimetro_revisiones"
    repo.client = SimpleNamespace(table=lambda _: ControlQuery())

    assert repo.equipment_control_defaults("A", page_size=1) == {
        "equipment_type": "Ultrasónico",
        "equipment_serial": "EQ-A",
        "transducer_serial": "TR-A",
    }
    assert repo.equipment_control_defaults("B", page_size=1) == {
        "equipment_type": "Ultrasónico",
        "equipment_serial": "OTRO",
        "transducer_serial": "OTRO-T",
    }
