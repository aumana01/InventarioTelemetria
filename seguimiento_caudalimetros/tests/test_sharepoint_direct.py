import pytest

import src.sharepoint_repository as sharepoint_module
from src.sharepoint_repository import fetch_sharepoint_html_direct


class FakeResponse:
    def __init__(self, url, content, status_code=200, headers=None):
        self.url = url
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_sharepoint_html_direct_strips_web_viewer_query(monkeypatch):
    called_urls = []

    def fake_get(url, *args, **kwargs):
        called_urls.append(url)
        return FakeResponse(
            "https://tenant.sharepoint.com/sites/x/Lists/y/Attachments/10/grafico.html",
            b"<!doctype html><html><body><script>var grafico=1;</script></body></html>",
            headers={"Content-Disposition": 'attachment; filename="grafico.html"'},
        )

    monkeypatch.setattr(sharepoint_module.requests, "get", fake_get)

    filename, content = fetch_sharepoint_html_direct(
        "https://tenant.sharepoint.com/sites/x/Lists/y/Attachments/10/grafico.html?web=1"
    )

    assert called_urls[0].endswith("/Attachments/10/grafico.html")
    assert "?web=1" not in called_urls[0]
    assert filename == "grafico.html"
    assert b"grafico" in content


def test_fetch_sharepoint_html_direct_skips_sharepoint_shell(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return FakeResponse(
                "https://tenant.sharepoint.com/_layouts/15/WopiFrame.aspx",
                b"<html><script src='/_layouts/15/init.js'></script>SharePoint Page</html>",
            )
        return FakeResponse(
            "https://tenant.sharepoint.com/sites/x/Lists/y/Attachments/10/grafico.html",
            b"<!doctype html><html><body>grafico real</body></html>",
            headers={"Content-Disposition": 'attachment; filename="grafico.html"'},
        )

    monkeypatch.setattr(sharepoint_module.requests, "get", fake_get)

    _, content = fetch_sharepoint_html_direct(
        "https://tenant.sharepoint.com/sites/x/Lists/y/Attachments/10/grafico.html?web=1"
    )
    assert b"grafico real" in content
    assert calls["count"] == 2


def test_fetch_sharepoint_html_direct_detects_login_redirect(monkeypatch):
    monkeypatch.setattr(
        sharepoint_module.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            "https://login.microsoftonline.com/common/oauth2/authorize",
            b"<html>Sign in to your account</html>",
        ),
    )
    with pytest.raises(RuntimeError, match="No fue posible obtener el HTML real"):
        fetch_sharepoint_html_direct(
            "https://tenant.sharepoint.com/sites/x/Lists/y/Attachments/10/grafico.html"
        )


def test_fetch_sharepoint_html_direct_rejects_other_hosts():
    with pytest.raises(ValueError):
        fetch_sharepoint_html_direct("https://example.com/grafico.html")
