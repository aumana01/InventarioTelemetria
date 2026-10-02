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
