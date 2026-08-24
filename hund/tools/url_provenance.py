"""Session-isolated exact-URL authority for web tools."""
from __future__ import annotations

from dataclasses import dataclass
import re
import threading
import time
from urllib.parse import urlsplit, urlunsplit

_URL_RE = re.compile(r"https?://[^\s<>\]\[(){}\"']+", re.IGNORECASE)
_PERCENT_RE = re.compile(r"%[0-9a-fA-F]{2}")


def canonicalize_url(url: str) -> str:
    """Canonicalize an exact HTTP(S) URL without changing query semantics."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL is required")
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ValueError("only http/https URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL userinfo is forbidden")
    if not parsed.hostname:
        raise ValueError("URL host is required")
    try:
        host = parsed.hostname.encode("idna").decode("ascii").casefold()
        port = parsed.port
    except (UnicodeError, ValueError) as exc:
        raise ValueError("invalid URL host or port") from exc
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = 80 if scheme == "http" else 443
    netloc = host if port in (None, default_port) else f"{host}:{port}"

    def uppercase_percent(value: str) -> str:
        return _PERCENT_RE.sub(lambda match: match.group(0).upper(), value)

    path = uppercase_percent(parsed.path or "/")
    query = uppercase_percent(parsed.query)
    return urlunsplit((scheme, netloc, path, query, ""))


@dataclass(frozen=True)
class UrlAuthority:
    url: str
    source: str
    expires_at: float


class UrlProvenanceStore:
    """Bounded, thread-safe URL allowlist for exactly one session."""

    def __init__(
        self,
        session_id: str,
        *,
        ttl_seconds: float = 3600.0,
        max_urls: int = 500,
        clock=time.monotonic,
    ) -> None:
        self.session_id = session_id
        self.ttl_seconds = ttl_seconds
        self.max_urls = max_urls
        self._clock = clock
        self._entries: dict[str, UrlAuthority] = {}
        self._lock = threading.RLock()

    def _prune(self) -> None:
        now = self._clock()
        expired = [url for url, entry in self._entries.items() if entry.expires_at <= now]
        for url in expired:
            self._entries.pop(url, None)

    def register_url(self, url: str, source: str) -> None:
        canonical = canonicalize_url(url)
        with self._lock:
            self._prune()
            if canonical not in self._entries and len(self._entries) >= self.max_urls:
                oldest = min(self._entries.values(), key=lambda entry: entry.expires_at)
                self._entries.pop(oldest.url, None)
            self._entries[canonical] = UrlAuthority(
                canonical, source, self._clock() + self.ttl_seconds
            )

    def register_user_text(self, text: str) -> int:
        added = 0
        for match in _URL_RE.findall(text or ""):
            candidate = match.rstrip(".,;:!?")
            try:
                self.register_url(candidate, "user_message")
                added += 1
            except ValueError:
                continue
        return added

    def is_allowed(self, url: str) -> bool:
        try:
            canonical = canonicalize_url(url)
        except ValueError:
            return False
        with self._lock:
            self._prune()
            return canonical in self._entries

    def source_for(self, url: str) -> str | None:
        try:
            canonical = canonicalize_url(url)
        except ValueError:
            return None
        with self._lock:
            self._prune()
            entry = self._entries.get(canonical)
            return entry.source if entry else None


_SESSION_STORES: dict[str, UrlProvenanceStore] = {}
_SESSION_LOCK = threading.RLock()


def get_url_provenance_store(session_id: str) -> UrlProvenanceStore:
    """Get the isolated authority store for a session."""
    with _SESSION_LOCK:
        store = _SESSION_STORES.get(session_id)
        if store is None:
            store = UrlProvenanceStore(session_id)
            _SESSION_STORES[session_id] = store
        return store


def clear_url_provenance_store(session_id: str) -> None:
    with _SESSION_LOCK:
        _SESSION_STORES.pop(session_id, None)
