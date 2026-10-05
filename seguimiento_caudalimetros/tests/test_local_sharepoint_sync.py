from sincronizar_html_sharepoint import canonical_attachment_url, is_microsoft_login_url


def test_canonical_attachment_url_removes_web_query():
    url = (
        "https://tenant.sharepoint.com/sites/demo/Lists/x/"
        "Attachments/2013/grafico_caudals.html?web=1"
    )
    assert canonical_attachment_url(url).endswith(
        "/Attachments/2013/grafico_caudals.html"
    )
    assert "?" not in canonical_attachment_url(url)


def test_login_url_detection():
    assert is_microsoft_login_url(
        "https://login.microsoftonline.com/common/oauth2/authorize"
    )
    assert not is_microsoft_login_url(
        "https://tenant.sharepoint.com/sites/demo"
    )
