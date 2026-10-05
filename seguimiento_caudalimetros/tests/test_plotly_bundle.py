from pathlib import Path

import plotly


def test_plotly_python_bundle_contains_plotly_js_3_0_1():
    path = Path(plotly.__file__).resolve().parent / "package_data" / "plotly.min.js"
    assert path.exists()
    header = path.read_text(encoding="utf-8")[:500]
    assert "plotly.js v3.0.1" in header
