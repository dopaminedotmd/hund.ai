"""Redactor v2 — utökad privacy-sanitizer (komposition över TCB redactor.py).

Använder RedactionResult från redactor.py för bakåtkompatibilitet.
Lägger till nya mönster: IP-adresser, telefonnummer, UUID, URL-query-params,
datum i sökvägar, svenska personnummer, access keys, base64-strängar.

RedactableConfig styr vilka mönster som är aktiva.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .redactor import RedactionResult, redact_text


@dataclass
class RedactableConfig:
    """Konfiguration för Redactor v2 — aktivera/inaktivera mönster.

    Alla mönster är aktiva som default. Sätt till False för att utesluta.
    """

    ip_addresses: bool = True
    phone_numbers: bool = True
    uuids: bool = True
    url_query_params: bool = True
    date_paths: bool = True
    swedish_ssn: bool = True
    access_keys: bool = True
    base64_strings: bool = True
    # V1-mönster (alltid aktiva, kan inte inaktiveras via config)
    # secrets, emails, paths, long_text truncation


_V2_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    # Order matters: more specific patterns first to avoid false matches
    # 1. UUID/GUID (8-4-4-4-12)
    ("uuids",
     re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
     "[REDACTED:uuid]"),
    # 2. IPv4-adresser
    ("ip_addresses",
     re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"),
     "[REDACTED:ip]"),
    # 3. IPv6-adresser
    ("ip_addresses",
     re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"),
     "[REDACTED:ip]"),
    ("ip_addresses",
     re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){1,7}:\b"),
     "[REDACTED:ip]"),
    # 4. Datum/tid i path-format (YYYY-MM-DD, YYYY/MM/DD) — before phone/SSN
    ("date_paths",
     re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b"),
     "[REDACTED:date]"),
    # 5. Access keys (AWS-style: AKIA*, etc.) — before base64
    ("access_keys",
     re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
     "[REDACTED:access_key]"),
    ("access_keys",
     re.compile(r"(?i)\b(?:sk-[a-z0-9]{32}|pk-[a-z0-9]{32})\b"),
     "[REDACTED:access_key]"),
    # 6. Svenska personnummer (YYYYMMDD-XXXX)
    ("swedish_ssn",
     re.compile(r"\b(?:19|20)?\d{6}[-]?\d{4}\b"),
     "[REDACTED:personnummer]"),
    # 7. Telefonnummer (internationella + lokala) — last in numeric group
    ("phone_numbers",
     re.compile(r"\b\+?[1-9]\d{1,3}[-\s]?\d{2,3}[-\s]?\d{2,3}[-\s]?\d{2,4}\b"),
     "[REDACTED:phone]"),
    # 8. Base64-strängar över 40 chars
    ("base64_strings",
     re.compile(r"\b(?:[A-Za-z0-9+/]{4}){10,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?\b"),
     "[REDACTED:base64]"),
]


def _redact_url_query_params(text: str) -> tuple[str, int]:
    """Redactera query-parametrar i URL:er, behåll basURL."""
    pattern = re.compile(r"(https?://[^\s?]+)\?([^\s]+)")
    count = 0

    def _repl(m: re.Match) -> str:
        nonlocal count
        count += 1
        base = m.group(1)
        # Behåll basURL, redactera query-params
        return f"{base}?[REDACTED:query]"

    return pattern.sub(_repl, text), count


def redact_text_v2(
    text: str,
    config: RedactableConfig | None = None,
    *,
    max_chars: int = 4000,
) -> RedactionResult:
    """Redaktera text med v1 + v2-mönster.

    Först körs v1-redaction (redact_text) för bakåtkompatibilitet.
    Därefter appliceras v2-mönster enligt config.

    Args:
        text: Text att redaktera.
        config: RedactableConfig för att styra vilka mönster som aktiveras.
        max_chars: Maximal teckenlängd innan trunkering (förs vidare till v1).

    Returns:
        RedactionResult med redakterad text och blockerade fält.
    """
    if config is None:
        config = RedactableConfig()

    # 1. V1-redaction (alltid)
    v1_result = redact_text(text, max_chars=max_chars)
    out = v1_result.text
    blocked = list(v1_result.blocked_fields)

    # 2. URL query-parameter redaction
    if config.url_query_params:
        out, n = _redact_url_query_params(out)
        if n and "url_query" not in blocked:
            blocked.append("url_query")

    # 3. V2-mönster
    for field, pattern, replacement in _V2_PATTERNS:
        enabled = getattr(config, field, True)
        if not enabled:
            continue
        out, n = pattern.subn(replacement, out)
        if n and field not in blocked:
            blocked.append(field)

    # 4. Risk level
    risk = "review_required" if blocked else "safe"
    # Escalera till blocked om vissa högriskmönster hittades
    high_risk = {"secret", "access_keys", "base64_strings"}
    if blocked and any(f in high_risk for f in blocked):
        risk = "blocked"

    return RedactionResult(text=out, blocked_fields=blocked, risk_level=risk)
