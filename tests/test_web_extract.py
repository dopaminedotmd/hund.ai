"""Tests for web_extract tool."""
import pytest
from unittest.mock import patch, MagicMock
import httpx

from hund.tools.web_extract import extract_web


def test_extract_web_missing_url():
    """Om url saknas, returnera felmeddelande."""
    res = extract_web({})
    assert "[error] url saknas" in res


def test_extract_web_invalid_protocol():
    """Om url inte startar med http:// eller https://, returnera felmeddelande."""
    res = extract_web({"url": "ftp://ftp.example.com"})
    assert "[error] url maste borja med" in res


def test_extract_web_success():
    """Om hämtning lyckas, rensa HTML och returnera texten."""
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "text/html; charset=utf-8"}
    mock_response.text = (
        "<html>"
        "<head><style>body { color: red; }</style></head>"
        "<body>"
        "<h1>Hello World</h1>"
        "<script>console.log('test');</script>"
        "<p>This is a paragraph.</p>"
        "</body>"
        "</html>"
    )
    
    with patch("httpx.get", return_value=mock_response) as mock_get:
        res = extract_web({"url": "https://example.com"})
        mock_get.assert_called_once_with(
            "https://example.com",
            timeout=10,
            follow_redirects=True,
            headers={"User-Agent": "Hund/1.0 (CLI agent)"}
        )
        # HTML taggar, script och style ska vara borta
        assert "Hello World This is a paragraph." in res
        assert "body {" not in res
        assert "console.log" not in res


def test_extract_web_unsupported_content_type():
    """Om content-type inte stöds (t.ex. application/pdf), returnera felmeddelande."""
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "application/pdf"}
    
    with patch("httpx.get", return_value=mock_response):
        res = extract_web({"url": "https://example.com/doc.pdf"})
        assert "[error] content-type stods ej: application/pdf" in res


def test_extract_web_timeout():
    """Vid timeout, returnera '[error] timeout'."""
    with patch("httpx.get", side_effect=httpx.TimeoutException("Timeout occurred")):
        res = extract_web({"url": "https://example.com"})
        assert res == "[error] timeout"


def test_extract_web_http_error():
    """Vid HTTP-fel, returnera statuskod."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    
    with patch("httpx.get", side_effect=httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)):
        res = extract_web({"url": "https://example.com/notfound"})
        assert res == "[error] HTTP 404"


def test_extract_web_truncation():
    """Om texten överstiger 50KB, trunkera och lägg till markör."""
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "text/plain"}
    # Skapa 60KB text
    mock_response.text = "A" * 60_000
    
    with patch("httpx.get", return_value=mock_response):
        res = extract_web({"url": "https://example.com"})
        assert len(res) < 60_000
        assert "[TRUNCATD — output oversteg 50KB]" in res
        # Bör ha exakt 50_000 tecken plus markören
        assert res.startswith("A" * 50_000)
