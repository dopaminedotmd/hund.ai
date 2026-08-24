from __future__ import annotations

import pytest

from hund.tools.url_provenance import UrlProvenanceStore, canonicalize_url


def test_canonicalization_and_exact_authority():
    store = UrlProvenanceStore("one")
    store.register_url("HTTPS://Exämple.com:443/a%2fb?q=One#fragment", "user_message")
    assert store.is_allowed("https://xn--exmple-cua.com/a%2Fb?q=One")
    assert not store.is_allowed("https://xn--exmple-cua.com/a%2Fb?q=one")
    assert not store.is_allowed("https://xn--exmple-cua.com/other")


@pytest.mark.parametrize(
    "url",
    ["file:///tmp/a", "javascript:alert(1)", "https://user:pass@example.com/"],
)
def test_forbidden_url_forms(url: str):
    with pytest.raises(ValueError):
        canonicalize_url(url)


def test_user_message_seeding_and_session_isolation():
    first = UrlProvenanceStore("first")
    second = UrlProvenanceStore("second")
    assert first.register_user_text("open https://example.com/docs please") == 1
    assert first.is_allowed("https://example.com/docs")
    assert not second.is_allowed("https://example.com/docs")


def test_ttl_and_bounded_eviction():
    now = [0.0]
    store = UrlProvenanceStore(
        "bounded", ttl_seconds=10, max_urls=2, clock=lambda: now[0]
    )
    store.register_url("https://a.example/", "search")
    now[0] = 1
    store.register_url("https://b.example/", "search")
    now[0] = 2
    store.register_url("https://c.example/", "search")
    assert not store.is_allowed("https://a.example/")
    assert store.is_allowed("https://b.example/")
    now[0] = 12
    assert not store.is_allowed("https://b.example/")
