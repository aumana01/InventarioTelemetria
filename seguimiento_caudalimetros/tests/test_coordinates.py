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
