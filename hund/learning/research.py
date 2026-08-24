"""Bounded, gap-driven research with redaction and corroboration gates."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from ..store.sqlite import connect
from ..tools.web_search import search_web
from .ledger import append_event, enqueue_job, get_event
from .redactor import redact_text


_URL = re.compile(r"https?://[^\s]+")


@dataclass(frozen=True)
class ResearchResult:
    status: str
    searches: int = 0
    source_count: int = 0
    evidence_id: str = ""
    job_id: str = ""


def _gap_exists(gap_id: str, db_path: Path | str | None) -> bool:
    conn = connect(Path(db_path) if db_path else None)
    try:
        row = conn.execute("SELECT 1 FROM gap_events WHERE id = ?", (gap_id,)).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        conn.close()


def research_gap(
    gap_id: str,
    queries: list[str],
    *,
    verified_gap: bool,
    domain: str = "general",
    workspace_id: str = "",
    session_id: str = "",
    opt_out: bool = False,
    search: Callable[[dict], str] = search_web,
    db_path: Path | str | None = None,
) -> ResearchResult:
    """Run at most two read-only searches for an existing, verified gap.

    Web evidence is queued only after two independent source domains corroborate
    it. Unverified or single-source research receives no learning job and no XP.
    """
    if (
        opt_out
        or os.environ.get("HUND_GAP_RESEARCH", "1").strip().lower() in {"0", "false", "off"}
    ):
        return ResearchResult(status="opted_out")
    if not verified_gap or not _gap_exists(gap_id, db_path):
        return ResearchResult(status="unverified_gap")

    clean_queries = [redact_text(query).text for query in queries[:2] if query.strip()]
    results: list[str] = []
    sources: set[str] = set()
    for query in clean_queries:
        clean_result = redact_text(search({"query": query})).text
        results.append(f"query: {query}\n{clean_result}")
        for url in _URL.findall(clean_result):
            host = urlparse(url.rstrip(".,);")).hostname
            if host:
                sources.add(host.lower())

    if len(sources) < 2:
        return ResearchResult(
            status="insufficient_corroboration",
            searches=len(clean_queries),
            source_count=len(sources),
        )

    payload = "\n\n".join(results)
    fingerprint = hashlib.sha256(
        (gap_id + "\x1f" + payload).encode("utf-8")
    ).hexdigest()[:20]
    evidence_id = f"research_{fingerprint}"
    try:
        append_event(
            session_id=session_id,
            event_type="corroborated_research",
            source_type="web",
            source_ref=f"gap:{gap_id}",
            workspace_id=workspace_id,
            candidate_domains=[domain],
            payload=payload,
            event_id=evidence_id,
            db_path=db_path,
        )
    except Exception:
        if get_event(evidence_id, db_path=db_path) is None:
            return ResearchResult(
                status="storage_failed",
                searches=len(clean_queries),
                source_count=len(sources),
            )
    job_id = f"learnjob_{fingerprint}"
    enqueue_job([evidence_id], job_id=job_id, db_path=db_path)
    return ResearchResult(
        status="queued",
        searches=len(clean_queries),
        source_count=len(sources),
        evidence_id=evidence_id,
        job_id=job_id,
    )
