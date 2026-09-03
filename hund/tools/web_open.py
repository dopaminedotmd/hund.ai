"""Secure, provenance-gated web inspection with semantic page state."""
from __future__ import annotations

from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
import ipaddress
import re
import socket
import threading
import time
from typing import Any, Callable, Protocol
from urllib.parse import urljoin, urlsplit
import uuid

from .types import (
    ToolCallContext,
    ToolKind,
    ToolResult,
    ToolStatus,
    create_error_result,
    create_success_result,
)
from .url_provenance import canonicalize_url

MAX_BODY_BYTES = 1_048_576
MAX_REDIRECTS = 5
MAX_REGIONS = 50
MAX_NODE_CHARS = 10_000
SUMMARY_CHARS = 2_800
HARD_CONTEXT_CHARS = 6_000
ALLOWED_CONTENT_TYPES = {
    "text/html",
    "text/plain",
    "application/json",
    "application/xml",
    "text/xml",
    "text/markdown",
}


class BodyTooLarge(RuntimeError):
    pass


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


class WebTransport(Protocol):
    def fetch(self, url: str, pinned_ip: str, *, impersonate: str) -> TransportResponse: ...


class CurlCffiTransport:
    """curl_cffi transport with proxy isolation, DNS pinning and body cap."""

    def fetch(self, url: str, pinned_ip: str, *, impersonate: str) -> TransportResponse:
        from curl_cffi import CurlOpt, requests

        parsed = urlsplit(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        address = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
        resolve = f"{host}:{port}:{address}"
        session = requests.Session(
            trust_env=False,
            curl_options={
                CurlOpt.RESOLVE: [resolve],
                CurlOpt.CONNECTTIMEOUT_MS: 5_000,
                CurlOpt.TIMEOUT_MS: 15_000,
            },
        )
        response = None
        try:
            response = session.get(
                url,
                allow_redirects=False,
                stream=True,
                timeout=(5.0, 10.0),
                impersonate=impersonate,
                accept_encoding="identity",
                headers={"Accept-Encoding": "identity"},
            )
            body = bytearray()
            for chunk in response.iter_content(chunk_size=65_536):
                if not chunk:
                    continue
                if len(body) + len(chunk) > MAX_BODY_BYTES:
                    raise BodyTooLarge("response exceeded 1 MiB")
                body.extend(chunk)
            return TransportResponse(
                int(response.status_code),
                {str(k).casefold(): str(v) for k, v in response.headers.items()},
                bytes(body),
            )
        finally:
            if response is not None:
                response.close()
            session.close()


def resolve_public_ips(host: str) -> tuple[str, ...]:
    """Resolve host and reject it unless every returned address is public."""
    try:
        literal = ipaddress.ip_address(host)
        addresses = {literal}
    except ValueError:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    if not addresses:
        raise OSError("host resolved to no addresses")
    for address in addresses:
        if getattr(address, "ipv4_mapped", None) is not None or not address.is_global:
            raise PermissionError("destination resolved to a non-public address")
    return tuple(sorted(str(address) for address in addresses))


@dataclass(frozen=True)
class PageRegion:
    region_id: int
    kind: str
    text: str
    url: str | None = None


@dataclass
class PageState:
    page_id: str
    url: str
    title: str
    regions: list[PageRegion]
    created_at: float
    cursor: int = 0
    page_size: int = 5


class PageStateStore:
    def __init__(self, *, ttl_seconds: float = 900.0, max_pages: int = 10, clock=time.monotonic):
        self.ttl_seconds = ttl_seconds
        self.max_pages = max_pages
        self._clock = clock
        self._pages: dict[str, PageState] = {}
        self._lock = threading.RLock()

    def _prune(self) -> None:
        now = self._clock()
        for page_id in [
            key for key, page in self._pages.items()
            if page.created_at + self.ttl_seconds <= now
        ]:
            self._pages.pop(page_id, None)

    def put(self, page: PageState) -> None:
        with self._lock:
            self._prune()
            if page.page_id not in self._pages and len(self._pages) >= self.max_pages:
                oldest = min(self._pages.values(), key=lambda item: item.created_at)
                self._pages.pop(oldest.page_id, None)
            self._pages[page.page_id] = page

    def get(self, page_id: str) -> PageState | None:
        with self._lock:
            self._prune()
            return self._pages.get(page_id)


_PAGE_STORES: dict[str, PageStateStore] = {}
_PAGE_LOCK = threading.RLock()


def get_page_store(session_id: str) -> PageStateStore:
    with _PAGE_LOCK:
        return _PAGE_STORES.setdefault(session_id, PageStateStore())


class _SemanticHTMLParser(HTMLParser):
    _BLOCKS = {"p": "paragraph", "li": "paragraph", "pre": "code", "code": "code"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.regions: list[PageRegion] = []
        self.title = ""
        self._depth = 0
        self._skip = 0
        self._capture_kind: str | None = None
        self._capture_tag: str | None = None
        self._buffer: list[str] = []
        self._link_href: str | None = None
        self._link_buffer: list[str] = []
        self._in_title = False
        self._title_buffer: list[str] = []

    def _add(self, kind: str, text: str, url: str | None = None) -> None:
        clean = re.sub(r"\s+", " ", unescape(text)).strip()[:MAX_NODE_CHARS]
        if clean and len(self.regions) < MAX_REGIONS:
            self.regions.append(PageRegion(len(self.regions) + 1, kind, clean, url))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        self._depth += 1
        if tag in {"script", "style", "noscript", "template"}:
            self._skip += 1
            return
        if self._skip or self._depth > 15:
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            self._link_href = dict(attrs).get("href")
            self._link_buffer = []
        kind = "heading" if tag in {f"h{i}" for i in range(1, 7)} else self._BLOCKS.get(tag)
        if kind and self._capture_kind is None:
            self._capture_kind, self._capture_tag, self._buffer = kind, tag, []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "template"} and self._skip:
            self._skip -= 1
        elif not self._skip:
            if tag == "title":
                self._in_title = False
                self.title = re.sub(r"\s+", " ", "".join(self._title_buffer)).strip()[:300]
            if tag == "a" and self._link_href:
                self._add("link", "".join(self._link_buffer) or self._link_href, self._link_href)
                self._link_href = None
                self._link_buffer = []
            if tag == self._capture_tag and self._capture_kind:
                self._add(self._capture_kind, "".join(self._buffer))
                self._capture_kind = self._capture_tag = None
                self._buffer = []
        self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip or self._depth > 15:
            return
        if self._in_title:
            self._title_buffer.append(data)
        if self._capture_kind:
            self._buffer.append(data[:MAX_NODE_CHARS])
        if self._link_href:
            self._link_buffer.append(data[:MAX_NODE_CHARS])


def _decode(body: bytes, content_type: str) -> str:
    match = re.search(r"charset\s*=\s*['\"]?([^;\s'\"]+)", content_type, re.I)
    encoding = match.group(1) if match else "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _semantic_regions(text: str, content_type: str, base_url: str) -> tuple[str, list[PageRegion]]:
    if content_type == "text/html":
        parser = _SemanticHTMLParser()
        parser.feed(text)
        regions = [
            PageRegion(r.region_id, r.kind, r.text, urljoin(base_url, r.url) if r.url else None)
            for r in parser.regions
        ]
        return parser.title, regions
    clean = re.sub(r"\s+", " ", text).strip()
    return "", [PageRegion(1, "text", clean[:MAX_NODE_CHARS])] if clean else []


def _render_regions(page: PageState, regions: list[PageRegion], *, max_chars: int) -> str:
    lines = [f"[{page.page_id}] {page.title or page.url}"]
    for region in regions:
        suffix = f" -> {region.url}" if region.url else ""
        lines.append(f"{region.region_id}. {region.kind}: {region.text}{suffix}")
    rendered = "\n".join(lines)
    if len(rendered) > max_chars:
        rendered = rendered[:max_chars].rstrip() + "\n[TRUNCATED]"
    return rendered


class WebOpenService:
    def __init__(
        self,
        *,
        resolver: Callable[[str], tuple[str, ...]] = resolve_public_ips,
        transport: WebTransport | None = None,
        page_store: PageStateStore | None = None,
        clock=time.monotonic,
    ) -> None:
        self.resolver = resolver
        self.transport = transport or CurlCffiTransport()
        self.page_store = page_store or PageStateStore(clock=clock)
        self.clock = clock

    def _error(self, status: ToolStatus, public: str, raw: str = "") -> ToolResult:
        return create_error_result(status, ToolKind.WEB_PAGE, raw or public, public_error=public)

    def _fetch(self, url: str, context: ToolCallContext) -> ToolResult:
        if context.url_provenance is None or not context.url_provenance.is_allowed(url):
            return self._error(
                ToolStatus.BLOCKED,
                "URL:en är inte i sessionens provenienslista — öppna endast URL:er från web_search-resultat eller användaren",
            )
        try:
            current = canonicalize_url(url)
        except ValueError as exc:
            return self._error(ToolStatus.BLOCKED, "Invalid or unsupported URL", str(exc))

        response: TransportResponse | None = None
        for redirect_count in range(MAX_REDIRECTS + 1):
            try:
                host = urlsplit(current).hostname or ""
                ips = self.resolver(host)
                if not ips:
                    raise OSError("no public addresses")
                response = self.transport.fetch(current, ips[0], impersonate="chrome")
                if len(response.body) > MAX_BODY_BYTES:
                    raise BodyTooLarge("response exceeded 1 MiB")
            except PermissionError as exc:
                return self._error(ToolStatus.SSRF_BLOCKED, "Destination address blocked", str(exc))
            except BodyTooLarge as exc:
                return self._error(ToolStatus.NETWORK_ERROR, "Response exceeded 1 MiB limit", str(exc))
            except Exception as exc:
                try:
                    host = urlsplit(current).hostname or ""
                    ips = self.resolver(host)
                    if not ips:
                        raise OSError("no public addresses")
                    response = self.transport.fetch(current, ips[0], impersonate="firefox")
                    if len(response.body) > MAX_BODY_BYTES:
                        raise BodyTooLarge("response exceeded 1 MiB")
                except PermissionError as p_exc:
                    return self._error(ToolStatus.SSRF_BLOCKED, "Destination address blocked", str(p_exc))
                except BodyTooLarge as b_exc:
                    return self._error(ToolStatus.NETWORK_ERROR, "Response exceeded 1 MiB limit", str(b_exc))
                except Exception as retry_exc:
                    return self._error(
                        ToolStatus.NETWORK_ERROR,
                        "nätverksfel — försök igen en gång eller välj annan källa",
                        f"{exc}; fallback: {retry_exc}",
                    )

            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    return self._error(ToolStatus.NETWORK_ERROR, "Redirect lacked Location header")
                if redirect_count >= MAX_REDIRECTS:
                    return self._error(ToolStatus.NETWORK_ERROR, "Too many redirects")
                try:
                    current = canonicalize_url(urljoin(current, location))
                except ValueError as exc:
                    return self._error(ToolStatus.BLOCKED, "Redirect URL was invalid", str(exc))
                continue
            break

        assert response is not None
        if response.status_code in {403, 406}:
            try:
                host = urlsplit(current).hostname or ""
                ips = self.resolver(host)
                response = self.transport.fetch(current, ips[0], impersonate="firefox")
                if len(response.body) > MAX_BODY_BYTES:
                    raise BodyTooLarge("response exceeded 1 MiB")
            except BodyTooLarge as exc:
                return self._error(
                    ToolStatus.NETWORK_ERROR, "Response exceeded 1 MiB limit", str(exc)
                )
            except Exception as exc:
                return self._error(
                    ToolStatus.NETWORK_ERROR,
                    "nätverksfel — försök igen en gång eller välj annan källa",
                    str(exc),
                )
        status_map = {
            401: (ToolStatus.AUTH_REQUIRED, "Authentication required"),
            404: (ToolStatus.NOT_FOUND, "Page not found"),
            429: (ToolStatus.RATE_LIMITED, "Rate limited"),
        }
        if response.status_code in status_map:
            status, message = status_map[response.status_code]
            return self._error(status, message)
        if response.status_code in {403, 406}:
            return self._error(
                ToolStatus.BOT_CHALLENGE,
                "sajten blockerar automatisk läsning — gå vidare till nästa källa",
            )
        if not 200 <= response.status_code < 300:
            return self._error(
                ToolStatus.NETWORK_ERROR,
                "nätverksfel — försök igen en gång eller välj annan källa",
                f"HTTP {response.status_code}",
            )

        raw_content_type = response.headers.get("content-type", "").strip()
        content_type = raw_content_type.split(";", 1)[0].strip().casefold()
        if content_type not in ALLOWED_CONTENT_TYPES:
            return self._error(ToolStatus.UNSUPPORTED_CONTENT, "Unsupported content type")
        text = _decode(response.body, raw_content_type)
        lower = text.casefold()
        if any(marker in lower for marker in ("cf-chl-", "cloudflare challenge", "captcha")):
            return self._error(
                ToolStatus.BOT_CHALLENGE,
                "sajten blockerar automatisk läsning — gå vidare till nästa källa",
            )
        title, regions = _semantic_regions(text, content_type, current)
        if not regions:
            if "<script" in lower:
                return self._error(
                    ToolStatus.JAVASCRIPT_REQUIRED,
                    "sidan kräver JavaScript som inte kan köras — välj en annan källa från sökresultaten",
                )
            return ToolResult(ToolStatus.EMPTY, ToolKind.WEB_PAGE)

        page = PageState(uuid.uuid4().hex[:12], current, title, regions, self.clock())
        self.page_store.put(page)
        for region in regions:
            if region.url:
                try:
                    context.url_provenance.register_url(region.url, f"web_open:{page.page_id}")
                except ValueError:
                    pass
        payload = _render_regions(page, regions[: page.page_size], max_chars=SUMMARY_CHARS)
        return create_success_result(
            ToolKind.WEB_PAGE,
            payload,
            safe_provenance={
                "url": current,
                "title": title,
                "source": "web",
                "trust": "untrusted_external_content",
            },
            metadata={"page_id": page.page_id, "region_count": len(regions)},
        )

    def open(self, args: dict[str, Any], context: ToolCallContext) -> ToolResult:
        url = args.get("url")
        if isinstance(url, str) and url:
            return self._fetch(url, context)
        page_id = str(args.get("page_id", ""))
        page = self.page_store.get(page_id)
        if page is None:
            return self._error(ToolStatus.NOT_FOUND, "Page state not found or expired")
        if "read" in args:
            try:
                region_id = int(args["read"])
            except (TypeError, ValueError):
                return self._error(ToolStatus.ERROR, "read must be a numeric region id")
            regions = [region for region in page.regions if region.region_id == region_id]
            if not regions:
                return self._error(ToolStatus.NOT_FOUND, "Region not found")
            payload = _render_regions(page, regions, max_chars=HARD_CONTEXT_CHARS)
        elif args.get("next"):
            page.cursor = min(page.cursor + page.page_size, len(page.regions))
            regions = page.regions[page.cursor : page.cursor + page.page_size]
            if not regions:
                return ToolResult(ToolStatus.EMPTY, ToolKind.WEB_PAGE)
            payload = _render_regions(page, regions, max_chars=SUMMARY_CHARS)
        elif isinstance(args.get("find"), str):
            needle = args["find"].casefold().strip()
            regions = [r for r in page.regions if needle and needle in r.text.casefold()][:10]
            if not regions:
                return ToolResult(ToolStatus.EMPTY, ToolKind.WEB_PAGE)
            payload = _render_regions(page, regions, max_chars=HARD_CONTEXT_CHARS)
        elif "follow" in args:
            try:
                link_id = int(args["follow"])
            except (TypeError, ValueError):
                return self._error(ToolStatus.ERROR, "follow must be a numeric link id")
            region = next((r for r in page.regions if r.region_id == link_id and r.url), None)
            if region is None:
                return self._error(ToolStatus.NOT_FOUND, "Link not found")
            return self._fetch(region.url or "", context)
        elif args.get("full"):
            payload = _render_regions(page, page.regions, max_chars=HARD_CONTEXT_CHARS)
        else:
            payload = _render_regions(page, page.regions[: page.page_size], max_chars=SUMMARY_CHARS)
        return create_success_result(
            ToolKind.WEB_PAGE,
            payload,
            safe_provenance={
                "url": page.url,
                "title": page.title,
                "source": "web",
                "trust": "untrusted_external_content",
            },
            metadata={"page_id": page.page_id, "region_count": len(page.regions)},
        )


def open_web(args: dict[str, Any], context: ToolCallContext | None) -> ToolResult:
    if context is None:
        return ToolResult(
            ToolStatus.BLOCKED,
            ToolKind.WEB_PAGE,
            public_error="web_open requires session context",
        )
    service = WebOpenService(page_store=get_page_store(context.session_id))
    return service.open(args, context)
