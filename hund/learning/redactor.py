"""Redactor — deterministisk privacy-sanitizer (TCB).

Syfte: skydda export/upload/proposals från att bära råa secrets, privata paths
eller stora råutdrag. Lokal fritext får finnas i HundHome, men allt som senare
kan lämna maskinen ska passera detta lager först.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionResult:
    text: str
    blocked_fields: list[str]
    risk_level: str = "safe"  # safe|review_required|blocked


_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[^\s,;]+"),
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\(?:[^\\\r\n\t:*?\"<>|]+\\?)+")
_POSIX_PRIVATE_PATH_RE = re.compile(r"(?<!\S)/(?:Users|home)/[^\s\r\n]+")


def _replace_all(text: str, patterns: tuple[re.Pattern[str], ...], repl: str) -> tuple[str, bool]:
    changed = False
    for pattern in patterns:
        text, n = pattern.subn(repl, text)
        changed = changed or n > 0
    return text, changed


def _append_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def redact_text(text: str, *, max_chars: int = 4000) -> RedactionResult:
    """Redaktera kända riskmönster och trunka långt råmaterial.

    Funktionen är avsiktligt deterministisk och dependency-free så den kan vara
    del av TCB och testas med fixtures.
    """
    blocked: list[str] = []
    out = text

    out, changed = _replace_all(out, _SECRET_PATTERNS, "[REDACTED:secret]")
    if changed:
        _append_once(blocked, "secret")

    out, n = _EMAIL_RE.subn("[REDACTED:email]", out)
    if n:
        _append_once(blocked, "email")

    out, n_win = _WINDOWS_PATH_RE.subn("[REDACTED:path]", out)
    out, n_posix = _POSIX_PRIVATE_PATH_RE.subn("[REDACTED:path]", out)
    if n_win or n_posix:
        _append_once(blocked, "path")

    if len(out) > max_chars:
        out = out[:max_chars].rstrip() + "\n[TRUNCATED]"
        _append_once(blocked, "long_text")

    risk = "review_required" if blocked else "safe"
    return RedactionResult(text=out, blocked_fields=blocked, risk_level=risk)


def build_export_preview(text: str, *, source: str = "manual") -> dict:
    """Bygg structured-only preview för data som skulle kunna exporteras.

    Inga råa prompts, svar, filinnehåll, terminalutdrag eller redakterad fritext
    inkluderas. V1-export ska bära metadata om Hunds prestation, inte
    användarens innehåll.
    """
    result = redact_text(text)
    return {
        "schema_version": 1,
        "source": source,
        "risk_level": result.risk_level,
        "blocked_fields": result.blocked_fields,
        "redactions_applied": bool(result.blocked_fields),
        "input_chars": len(text),
        "redacted_chars": len(result.text),
        "contains_text": False,
    }
