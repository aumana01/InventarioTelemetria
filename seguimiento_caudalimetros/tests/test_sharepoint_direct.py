from types import SimpleNamespace

import pytest

import src.sharepoint_repository as sharepoint_module
from src.sharepoint_repository import fetch_sharepoint_html_direct


class FakeResponse:
    def __init__(self, url, content, status_code=200):
        self.url = url
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_sharepoint_html_direct(monkeypatch):
    monkeypatch.setattr(
        sharepoint_module.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            "https://tenant.sharepoint.com/sites/x/Lists/y/Attachments/10/grafico.html",
            b"<!doctype html><html><body>grafico</body></html>",
        ),
    )
    filename, content = fetch_sharepoint_html_direct(
        "https://tenant.sharepoint.com/sites/x/Lists/y/Attachments/10/grafico.html?web=1"
    )
    assert filename == "grafico.html"
    assert b"grafico" in content


def test_fetch_sharepoint_html_direct_detects_login_redirect(monkeypatch):
    monkeypatch.setattr(
        sharepoint_module.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            "https://login.microsoftonline.com/common/oauth2/authorize",
            b"<html>Sign in to your account</html>",
        ),
    )
    with pytest.raises(PermissionError):
        fetch_sharepoint_html_direct(
            "https://tenant.sharepoint.com/sites/x/Lists/y/Attachments/10/grafico.html"
        )


def test_fetch_sharepoint_html_direct_rejects_other_hosts():
    with pytest.raises(ValueError):
        fetch_sharepoint_html_direct("https://example.com/grafico.html")
