from pathlib import Path


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"


def test_plotly_toolbar_is_horizontal_and_enhanced():
    js = (ASSET_DIR / "graph_component.js").read_text(encoding="utf-8")
    css = (ASSET_DIR / "graph_component.css").read_text(encoding="utf-8")

    assert 'orientation: "h"' in js
    assert 'displayModeBar: true' in js
    assert 'scrollZoom: true' in js
    assert '"drawline"' in js
    assert '"drawrect"' in js
    assert '"drawcircle"' in js
    assert '"eraseshape"' in js
    assert '"toggleSpikelines"' in js
    assert '"hoverClosestCartesian"' in js
    assert '"hoverCompareCartesian"' in js
    assert 'format: "png"' in js
    assert "flex-direction: row" in css
