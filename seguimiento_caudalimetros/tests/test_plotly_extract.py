from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


AGENT_MODULE = (
    Path(__file__).resolve().parents[2]
    / "agente_sharepoint"
    / "plotly_extract.py"
)

spec = importlib.util.spec_from_file_location("plotly_extract_agent", AGENT_MODULE)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_extracts_plotly_newplot_and_compresses():
    html = """
    <html><body>
    <div id="abc"></div>
    <script>
    Plotly.newPlot(
      "abc",
      [{"type":"scatter","x":[1,2,3],"y":[4,5,6],"name":"Caudal"}],
      {"title":{"text":"Prueba"},"width":900,"height":500},
      {"responsive":true}
    );
    </script>
    </body></html>
    """

    figures = module.extract_plotly_figures(html)
    assert len(figures) == 1
    assert figures[0]["data"][0]["name"] == "Caudal"
    assert figures[0]["layout"]["autosize"] is True
    assert "width" not in figures[0]["layout"]
    assert "height" not in figures[0]["layout"]

    compact = module.compact_plotly_html("grafico.html", html.encode("utf-8"))
    assert compact.filename == "grafico.plotly.json.gz"
    assert compact.figure_count == 1

    import gzip

    payload = json.loads(gzip.decompress(compact.content).decode("utf-8"))
    assert payload["format"] == "plotly"
    assert payload["plotly_js_version"] == "3.0.1"
    assert payload["figures"][0]["data"][0]["y"] == [4, 5, 6]


def test_multiple_plotly_figures_are_supported():
    html = """
    <script>
    Plotly.newPlot("a",[{"x":[1],"y":[2]}],{"title":"A"},{"responsive":true});
    Plotly.newPlot("b",[{"x":[3],"y":[4]}],{"title":"B"},{"responsive":true});
    </script>
    """
    figures = module.extract_plotly_figures(html)
    assert len(figures) == 2


def test_missing_plotly_call_is_rejected():
    try:
        module.extract_plotly_figures("<html><body>Sin gráfico</body></html>")
    except ValueError as exc:
        assert "Plotly.newPlot" in str(exc)
    else:
        raise AssertionError("Se esperaba ValueError")
