import pandas as pd
from pyproj import Transformer

from src.sql_repository import transform_crtm05_to_wgs84


def test_transform_crtm05_to_wgs84():
    inverse = Transformer.from_crs("EPSG:4326", "EPSG:5367", always_xy=True)
    x, y = inverse.transform(-84.0907, 9.9281)

    source = pd.DataFrame({"X_CRTM05": [x], "Y_CRTM05": [y]})
    result = transform_crtm05_to_wgs84(source)

    assert abs(float(result.iloc[0]["LONGITUD"]) - (-84.0907)) < 0.00001
    assert abs(float(result.iloc[0]["LATITUD"]) - 9.9281) < 0.00001
    assert int(result.iloc[0]["EPSG_WGS84"]) == 4326


def test_transform_preserves_rows_without_geometry():
    source = pd.DataFrame(
        {
            "OBJECTID": [1, 2],
            "X_CRTM05": [None, 500000.0],
            "Y_CRTM05": [None, 1100000.0],
        }
    )

    result = transform_crtm05_to_wgs84(source)

    assert len(result) == 2
    assert pd.isna(result.loc[0, "LONGITUD"])
    assert pd.isna(result.loc[0, "LATITUD"])
    assert pd.isna(result.loc[0, "EPSG_WGS84"])
    assert pd.notna(result.loc[1, "LONGITUD"])
    assert pd.notna(result.loc[1, "LATITUD"])
    assert int(result.loc[1, "EPSG_WGS84"]) == 4326


class _FakeCursor:
    def __init__(self, existing_views):
        self.existing_views = set(existing_views)
        self._match = False

    def execute(self, _sql, _schema, candidate):
        self._match = candidate in self.existing_views
        return self

    def fetchone(self):
        return (1,) if self._match else None


class _FakeConnection:
    def __init__(self, existing_views):
        self.existing_views = existing_views

    def cursor(self):
        return _FakeCursor(self.existing_views)


def test_resolve_read_source_prefers_esri_versioned_view():
    from src.sql_repository import SqlMeterRepository

    conn = _FakeConnection({"MSG_Medidores_de_Caudal_evw"})
    result = SqlMeterRepository._resolve_read_source(
        conn,
        "AYA",
        "MSG_Medidores_de_Caudal",
    )

    assert result == "MSG_Medidores_de_Caudal_evw"


def test_resolve_read_source_falls_back_to_base_table():
    from src.sql_repository import SqlMeterRepository

    conn = _FakeConnection(set())
    result = SqlMeterRepository._resolve_read_source(
        conn,
        "AYA",
        "MSG_Medidores_de_Caudal",
    )

    assert result == "MSG_Medidores_de_Caudal"
