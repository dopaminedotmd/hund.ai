from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from hund.tools.types import ToolCallContext, ToolStatus
from hund.tools.url_provenance import UrlProvenanceStore
from hund.tools.web_open import (
    MAX_BODY_BYTES,
    PageStateStore,
    TransportResponse,
    WebOpenService,
    resolve_public_ips,
)


class FakeTransport:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.calls: list[tuple[str, str, str]] = []

    def fetch(self, url: str, pinned_ip: str, *, impersonate: str):
        self.calls.append((url, pinned_ip, impersonate))
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


def response(status=200, body=b"<h1>Title</h1><p>Body</p>", **headers):
    base = {"content-type": "text/html; charset=utf-8"}
    base.update(headers)
    return TransportResponse(status, base, body)


def context(tmp_path: Path, url: str) -> ToolCallContext:
    provenance = UrlProvenanceStore("test")
    provenance.register_url(url, "user_message")
    return ToolCallContext("test", tmp_path, url_provenance=provenance)


def service(transport: FakeTransport, resolver=None):
    return WebOpenService(
        transport=transport,
        resolver=resolver or (lambda host: ("93.184.216.34",)),
        page_store=PageStateStore(),
    )


def test_unknown_url_is_blocked_before_dns_or_transport(tmp_path):
    transport = FakeTransport([])
    ctx = ToolCallContext("test", tmp_path, url_provenance=UrlProvenanceStore("test"))
    result = service(transport).open({"url": "https://example.com/"}, ctx)
    assert result.status is ToolStatus.BLOCKED
    assert transport.calls == []


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "::1", "10.0.0.1", "192.168.1.1", "169.254.169.254", "::ffff:127.0.0.1"],
)
def test_ssrf_addresses_are_blocked(address, monkeypatch):
    monkeypatch.setattr(
        "hund.tools.web_open.socket.getaddrinfo",
        lambda *a, **k: [(None, None, None, None, (address, 0))],
    )
    with pytest.raises(PermissionError):
        resolve_public_ips("example.test")


def test_mixed_public_private_dns_blocks_entire_host(tmp_path):
    def mixed(host):
        raise PermissionError("mixed DNS contained private address")

    transport = FakeTransport([])
    result = service(transport, mixed).open(
        {"url": "https://example.com/"}, context(tmp_path, "https://example.com/")
    )
    assert result.status is ToolStatus.SSRF_BLOCKED
    assert transport.calls == []


def test_redirect_to_private_destination_is_blocked(tmp_path):
    transport = FakeTransport([response(302, b"", location="http://metadata.test/")])

    def resolver(host):
        if host == "metadata.test":
            raise PermissionError("private")
        return ("93.184.216.34",)

    result = service(transport, resolver).open(
        {"url": "https://example.com/"}, context(tmp_path, "https://example.com/")
    )
    assert result.status is ToolStatus.SSRF_BLOCKED
    assert len(transport.calls) == 1


def test_delivered_body_limit_is_enforced_against_transport(tmp_path):
    transport = FakeTransport([
        TransportResponse(200, {"content-type": "text/plain"}, b"x" * (MAX_BODY_BYTES + 1))
    ])
    result = service(transport).open(
        {"url": "https://example.com/"}, context(tmp_path, "https://example.com/")
    )
    assert result.status is ToolStatus.NETWORK_ERROR
    assert "1 MiB" in (result.public_error or "")


def test_semantic_page_navigation_and_follow(tmp_path):
    first = b"<title>Docs</title><h1>Intro</h1><p>Alpha body</p><a href='/next?token=secret'>Next</a>"
    second = b"<h1>Next page</h1><p>Beta body</p>"
    transport = FakeTransport([response(body=first), response(body=second)])
    ctx = context(tmp_path, "https://example.com/docs")
    web = service(transport)

    opened = web.open({"url": "https://example.com/docs"}, ctx)
    assert opened.status is ToolStatus.SUCCESS
    assert opened.metadata["region_count"] >= 3
    page_id = opened.metadata["page_id"]
    assert opened.safe_provenance["trust"] == "untrusted_external_content"

    found = web.open({"page_id": page_id, "find": "alpha"}, ctx)
    assert "Alpha body" in found.to_llm_text()
    page = web.page_store.get(page_id)
    assert page is not None
    link = next(region for region in page.regions if region.url)
    assert ctx.url_provenance is not None
    assert ctx.url_provenance.is_allowed(link.url or "")

    followed = web.open({"page_id": page_id, "follow": link.region_id}, ctx)
    assert followed.status is ToolStatus.SUCCESS
    assert "Next page" in followed.to_llm_text()
    assert "token=secret" not in followed.to_llm_text()


def test_status_classification_and_browser_fallback(tmp_path):
    transport = FakeTransport([response(403), response(200, body=b"<p>ok</p>")])
    result = service(transport).open(
        {"url": "https://example.com/"}, context(tmp_path, "https://example.com/")
    )
    assert result.status is ToolStatus.SUCCESS
    assert [call[2] for call in transport.calls] == ["chrome", "firefox"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, ToolStatus.AUTH_REQUIRED), (404, ToolStatus.NOT_FOUND), (429, ToolStatus.RATE_LIMITED)],
)
def test_direct_status_classification(status, expected, tmp_path):
    transport = FakeTransport([response(status)])
    result = service(transport).open(
        {"url": "https://example.com/"}, context(tmp_path, "https://example.com/")
    )
    assert result.status is expected
    assert len(transport.calls) == 1


def test_unsupported_and_javascript_only_content(tmp_path):
    pdf = FakeTransport([TransportResponse(200, {"content-type": "application/pdf"}, b"pdf")])
    result = service(pdf).open(
        {"url": "https://example.com/a.pdf"}, context(tmp_path, "https://example.com/a.pdf")
    )
    assert result.status is ToolStatus.UNSUPPORTED_CONTENT

    js = FakeTransport([response(body=b"<script>renderApp()</script>")])
    result = service(js).open(
        {"url": "https://example.com/app"}, context(tmp_path, "https://example.com/app")
    )
    assert result.status is ToolStatus.JAVASCRIPT_REQUIRED
    assert result.public_error == "sidan kräver JavaScript som inte kan köras — välj en annan källa från sökresultaten"
    assert "[javascript_required] sidan kräver JavaScript som inte kan köras — välj en annan källa från sökresultaten" in result.to_llm_text()


def test_fetch_exception_triggers_firefox_fallback_success(tmp_path):
    transport = FakeTransport([RuntimeError("connection reset"), response(200, body=b"<p>recovered</p>")])
    result = service(transport).open(
        {"url": "https://example.com/"}, context(tmp_path, "https://example.com/")
    )
    assert result.status is ToolStatus.SUCCESS
    assert [call[2] for call in transport.calls] == ["chrome", "firefox"]
    assert "recovered" in result.payload


def test_fetch_exception_firefox_fallback_fails(tmp_path):
    transport = FakeTransport([RuntimeError("connection reset"), RuntimeError("fallback reset")])
    result = service(transport).open(
        {"url": "https://example.com/"}, context(tmp_path, "https://example.com/")
    )
    assert result.status is ToolStatus.NETWORK_ERROR
    assert [call[2] for call in transport.calls] == ["chrome", "firefox"]
    assert result.public_error == "nätverksfel — försök igen en gång eller välj annan källa"
    assert "[network_error] nätverksfel — försök igen en gång eller välj annan källa" in result.to_llm_text()


def test_guidance_error_messages(tmp_path):
    # 1. Provenance blocked
    transport = FakeTransport([])
    ctx_empty = ToolCallContext("test", tmp_path, url_provenance=UrlProvenanceStore("test"))
    res_blocked = service(transport).open({"url": "https://not-allowed.com/"}, ctx_empty)
    assert res_blocked.status is ToolStatus.BLOCKED
    assert res_blocked.public_error == "URL:en är inte i sessionens provenienslista — öppna endast URL:er från web_search-resultat eller användaren"
    assert "[blocked] URL:en är inte i sessionens provenienslista — öppna endast URL:er från web_search-resultat eller användaren" in res_blocked.to_llm_text()

    # 2. Bot challenge on 403
    bot_transport = FakeTransport([response(403), response(403)])
    res_bot = service(bot_transport).open(
        {"url": "https://example.com/"}, context(tmp_path, "https://example.com/")
    )
    assert res_bot.status is ToolStatus.BOT_CHALLENGE
    assert res_bot.public_error == "sajten blockerar automatisk läsning — gå vidare till nästa källa"
    assert "[bot_challenge] sajten blockerar automatisk läsning — gå vidare till nästa källa" in res_bot.to_llm_text()

