from types import SimpleNamespace

import src.supabase_repository as repository_module
from src.supabase_repository import SupabaseMeterRepository


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
