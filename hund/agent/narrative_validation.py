"""Provider-independent narrative validation and bounded repair for Phase 4.

Validates natural language narrative blocks for third-person Swedish persona and emoji/protocol
cleanliness while strictly preserving code blocks, diffs, quotations, receipts, and file paths.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Optional, Sequence


@dataclass(frozen=True)
class ContentBlock:
    """Typed content slice extracted from assistant response."""

    text: str
    is_narrative: bool  # True if natural prose; False if code, quote, receipt, path, or diff


@dataclass(frozen=True)
class NarrativeValidationResult:
    """Outcome of narrative validation check."""

    is_valid: bool
    violations: tuple[str, ...] = ()
    repaired_text: Optional[str] = None
    fallback_used: bool = False


# Regexes for extracting non-narrative regions
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_BLOCKQUOTE_RE = re.compile(r"^>[\s\S]*?(?=\n\n|\n[^\s>]|\Z)", re.MULTILINE)
_RECEIPT_CARD_RE = re.compile(r"^(?:[ ]{2,4}[◆◇│└┌].*|\s*╔[\s\S]*?╝)", re.MULTILINE)
_FILE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\[^\s\n]+|/(?:[\w.-]+/)+[\w.-]+)")

# Swedish first-person pronouns
_SWEDISH_FIRST_PERSON_RE = re.compile(r"\b(jag|mig|min|mitt|mina|mitts)\b", re.IGNORECASE)

# Emoji ranges (excluding standard ASCII, box drawing, and common math symbols)
_EMOJI_RE = re.compile(
    r"[\U0001F600-\U0001F64F"  # Emoticons
    r"\U0001F300-\U0001F5FF"  # Symbols & pictographs
    r"\U0001F680-\U0001F6FF"  # Transport & map
    r"\U0001F1E0-\U0001F1FF"  # Flags
    r"\U0001F900-\U0001F9FF"  # Supplemental symbols
    r"\U0001FA70-\U0001FAFF"  # Symbols extended
    r"\U00002702-\U000027B0"  # Dingbats
    r"\U000024C2-\U0001F251"
    r"]",
    re.UNICODE,
)

# Raw protocol leakage
_RAW_PROTOCOL_RE = re.compile(
    r"(?:<system>|<\|im_start\|>|<\|im_end\|>|tool_call_id|\[system\]|"
    r"<\s*/?\s*DSML[a-zA-Z0-9_]*(?:\s+[^>]*)?>|"
    r"\[\s*/?\s*TOOL_CALLS?\s*\]|"
    r"<\s*/?\s*(?:tool_calls?|tool_call|invoke|function_call)(?:\s+[^>]*)?>)",
    re.IGNORECASE,
)

# Persona mechanics recitation and naming violations
_HUNDEN_RE = re.compile(r"\bhunden\b", re.IGNORECASE)
_PERSONA_MECHANICS_DETECTION_RE = re.compile(
    r"\b(?:hund\s+(?:talar|pratar|skriver|svarar|uttrycker\s+sig)\s+(?:alltid\s+)?(?:i\s+)?tredje\s+person|"
    r"tredjepersons?(?:-|\s*)perspektiv|"
    r"tredjepersons?|"
    r"tredje\s+person|"
    r"third(?:-|\s+)person(?:\s+perspective)?|"
    r"speaks?\s+(?:in\s+)?third\s+person)\b",
    re.IGNORECASE,
)
_MALFORMED_ADDRESS_RE = re.compile(r"\bVill\s+hund\b", re.IGNORECASE)


def extract_content_blocks(full_text: str) -> list[ContentBlock]:
    """Segment full response into narrative prose vs protected non-narrative blocks."""
    if not full_text:
        return []

    # Find all protected spans (code fences, inline code, quotes, receipts)
    protected_spans: list[tuple[int, int]] = []

    for pattern in (
        _CODE_BLOCK_RE,
        _INLINE_CODE_RE,
        _BLOCKQUOTE_RE,
        _RECEIPT_CARD_RE,
        _FILE_PATH_RE,
    ):
        for m in pattern.finditer(full_text):
            protected_spans.append((m.start(), m.end()))

    if not protected_spans:
        return [ContentBlock(text=full_text, is_narrative=True)]

    # Merge overlapping spans
    protected_spans.sort(key=lambda x: x[0])
    merged: list[tuple[int, int]] = []
    for start, end in protected_spans:
        if not merged:
            merged.append((start, end))
        else:
            prev_start, prev_end = merged[-1]
            if start <= prev_end:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))

    blocks: list[ContentBlock] = []
    idx = 0
    for p_start, p_end in merged:
        if idx < p_start:
            prose_part = full_text[idx:p_start]
            if prose_part:
                blocks.append(ContentBlock(text=prose_part, is_narrative=True))
        blocks.append(ContentBlock(text=full_text[p_start:p_end], is_narrative=False))
        idx = p_end

    if idx < len(full_text):
        blocks.append(ContentBlock(text=full_text[idx:], is_narrative=True))

    return blocks


def validate_narrative_text(narrative: str, language: str = "sv") -> tuple[bool, list[str]]:
    """Check a narrative text block for persona, emoji, or protocol violations."""
    violations: list[str] = []

    # 1. Raw protocol leakage
    if _RAW_PROTOCOL_RE.search(narrative):
        violations.append("raw_protocol_leakage")

    # 2. Emojis
    if _EMOJI_RE.search(narrative):
        violations.append("emoji_present")

    # 3. Swedish first-person pronouns
    if language.lower().startswith("sv"):
        matches = _SWEDISH_FIRST_PERSON_RE.findall(narrative)
        if matches:
            violations.append(f"swedish_first_person:{','.join(set(m.lower() for m in matches))}")

    # 4. Hunden violation
    if _HUNDEN_RE.search(narrative):
        violations.append("persona_hunden_violation")

    # 5. Persona mechanics recitation
    if _PERSONA_MECHANICS_DETECTION_RE.search(narrative):
        violations.append("persona_mechanics_recitation")

    return len(violations) == 0, violations


def repair_narrative_prose(narrative: str, language: str = "sv") -> str:
    """Perform deterministic single-pass repair of common pronoun, emoji, and persona slips."""
    repaired = narrative

    # Strip emojis
    repaired = _EMOJI_RE.sub("", repaired)

    # Strip raw protocol tokens and blocks
    from ..providers.openai_compatible import filter_leaked_protocol
    repaired = filter_leaked_protocol(repaired)
    repaired = _RAW_PROTOCOL_RE.sub("", repaired)

    # Repair malformed user address
    repaired = _MALFORMED_ADDRESS_RE.sub("Vill du att hund", repaired)

    # Repair hunden -> hund
    repaired = re.sub(r"\bHunden\b", "Hund", repaired)
    repaired = re.sub(r"\bhunden\b", "hund", repaired)

    # Strip persona mechanics recitation by whole clauses/phrases
    # 1. Swedish whole-clause patterns
    repaired = re.sub(
        r"(?i)\bHund\s+(?:pratar|talar|skriver|svarar|uttrycker\s+sig)\s+(?:alltid\s+)?(?:i\s+)?tredje\s+person(?:s-?perspektiv)?\s*(?:,\s*och\s+|,\s*|\s+och\s+|\s*[—–-]\s*)",
        "hund ",
        repaired,
    )
    repaired = re.sub(
        r"(?i)\b(?:Eftersom\s+)?hund\s+(?:pratar|talar|skriver|svarar|använder)\s+(?:alltid\s+)?(?:i\s+)?tredjepersons?(?:-|\s*)perspektiv\s*(?:,\s*och\s+|,\s*|\s+och\s+|\s*[—–-]\s*|\s*\.\s*|\s*$)?",
        "",
        repaired,
    )
    repaired = re.sub(
        r"(?i)\bHund\s+(?:pratar|talar|skriver|svarar|uttrycker\s+sig)\s+(?:alltid\s+)?(?:i\s+)?tredje\s+person(?:s-?perspektiv)?\s*(?:\.\s*|\s*$)",
        "",
        repaired,
    )
    repaired = re.sub(
        r"(?i)\btredjepersons?(?:-|\s*)perspektiv\s*(?:,\s*och\s+|,\s*|\s+och\s+|\s*[—–-]\s*|\s*\.\s*|\s*$)?",
        "",
        repaired,
    )
    repaired = re.sub(
        r"(?i)\btredjepersons\s*(?:,\s*och\s+|,\s*|\s+och\s+|\s*[—–-]\s*)?",
        "",
        repaired,
    )
    repaired = re.sub(
        r"(?i)\bi\s+tredje\s+person(?:s-?perspektiv)?\s*(?:,\s*och\s+|,\s*|\s+och\s+|\s*[—–-]\s*|\s*\.\s*|\s*$)?",
        "",
        repaired,
    )
    repaired = re.sub(
        r"(?i)\btredje\s+person\s*(?:,\s*och\s+|,\s*|\s+och\s+|\s*[—–-]\s*|\s*\.\s*|\s*$)?",
        "",
        repaired,
    )

    # Clean leftover verb stubs if bare phrase removal left dangling verb
    repaired = re.sub(
        r"(?i)\bhund\s+(?:pratar|talar|skriver|svarar|uttrycker\s+sig)\s*(?:[—–-]|,\s*och\s+|,\s*|\s+och\s+)",
        "hund ",
        repaired,
    )
    repaired = re.sub(
        r"(?i)\bhund\s+(?:pratar|talar|skriver|svarar|uttrycker\s+sig)\s*(?:\.\s*|\s*$)",
        "",
        repaired,
    )

    # 2. English whole-clause patterns
    repaired = re.sub(
        r"(?i)\bAs\s+hund\s+speaks\s+(?:in\s+)?third(?:-|\s+)person(?:\s+perspective)?\s*(?:,\s*and\s+|,\s*|\s+and\s+|\s*[—–-]\s*)",
        "",
        repaired,
    )
    repaired = re.sub(
        r"(?i)\bHund\s+speaks\s+(?:in\s+)?third(?:-|\s+)person(?:\s+perspective)?\s*(?:,\s*and\s+|,\s*|\s+and\s+|\s*[—–-]\s*)",
        "Hund ",
        repaired,
    )
    repaired = re.sub(
        r"(?i)\bHund\s+speaks\s+(?:in\s+)?third(?:-|\s+)person(?:\s+perspective)?\s*(?:\.\s*|\s*$)",
        "",
        repaired,
    )
    repaired = re.sub(
        r"(?i)\bspeaks?\s+(?:in\s+)?third\s+person(?:\s+perspective)?\s*(?:,\s*and\s+|,\s*|\s+and\s+|\s*[—–-]\s*|\s*\.\s*|\s*$)?",
        "",
        repaired,
    )
    repaired = re.sub(
        r"(?i)\bthird(?:-|\s+)person(?:\s+perspective)?\s*(?:,\s*and\s+|,\s*|\s+and\s+|\s*[—–-]\s*|\s*\.\s*|\s*$)?",
        "",
        repaired,
    )
    repaired = re.sub(
        r"(?i)\bhund\s+speaks\s*(?:[—–-]|,\s*and\s+|,\s*|\s+and\s+)",
        "hund ",
        repaired,
    )

    # Repair Swedish first-person pronouns in natural prose
    if language.lower().startswith("sv"):
        repaired = re.sub(r"\b[Jj]ag\s+har\b", "hund har", repaired)
        repaired = re.sub(r"\b[Jj]ag\s+ser\b", "hund ser", repaired)
        repaired = re.sub(r"\b[Jj]ag\s+tycker\b", "hund tycker", repaired)
        repaired = re.sub(r"\b[Jj]ag\s+föreslår\b", "hund föreslår", repaired)
        repaired = re.sub(r"\b[Jj]ag\s+kan\b", "hund kan", repaired)
        repaired = re.sub(r"\b[Jj]ag\s+ska\b", "hund ska", repaired)
        repaired = re.sub(r"\b[Jj]ag\s+vill\b", "hund vill", repaired)
        repaired = re.sub(r"\b[Jj]ag\s+vet\b", "hund vet", repaired)
        repaired = re.sub(r"\b[Jj]ag\b", "hund", repaired)
        repaired = re.sub(r"\b[Mm]ig\b", "hund", repaired)
        repaired = re.sub(r"\b[Mm]in\b", "hunds", repaired)
        repaired = re.sub(r"\b[Mm]itt\b", "hunds", repaired)
        repaired = re.sub(r"\b[Mm]ina\b", "hunds", repaired)

    # Clean double spaces, orphaned punctuation
    repaired = re.sub(r"\s+([,.!?])", r"\1", repaired)
    repaired = re.sub(r"^[,\s]+", "", repaired)
    repaired = re.sub(r"[ ]{2,}", " ", repaired)
    if repaired and repaired[0].islower() and not repaired.startswith("hund"):
        repaired = repaired[0].upper() + repaired[1:]
    return repaired.strip()


def detect_unexecuted_tool_intent(text: str, registered_tools: Sequence[str]) -> bool:
    """Detect structural intent to execute a tool when no tool call was emitted."""
    if not text or not registered_tools:
        return False
    tool_pat = r"\b(?:" + "|".join(re.escape(t) for t in registered_tools) + r")\b"
    # Structural signals: tool name + action intent markers (SE/EN) or raw code fences
    intent_pat = re.compile(
        r"(?:"
        r"(?:låt hund|hund ska|hund kör|använder|kör)\s+.*?" + tool_pat +
        r"|(?:let me|i will|let hund|using|running)\s+.*?" + tool_pat +
        r"|" + tool_pat + r"\s+(?:för att|to)\s+"
        r"|```(?:bash|sh|powershell|pwsh|python)\s*\n[\s\S]*?```"
        r")",
        re.IGNORECASE,
    )
    return bool(intent_pat.search(text))


def validate_and_repair_response(
    full_response: str,
    language: str = "sv",
    repair_fn: Optional[Callable[[str, list[str]], str]] = None,
) -> tuple[str, NarrativeValidationResult]:
    """Validate full response, repairing narrative blocks while leaving code and quotes intact."""
    if not full_response:
        return "", NarrativeValidationResult(is_valid=True)

    blocks = extract_content_blocks(full_response)
    all_violations: list[str] = []
    reconstructed: list[str] = []
    any_repaired = False
    fallback_needed = False

    for block in blocks:
        if not block.is_narrative:
            # Protected block (code, diff, quote, receipt, path) — byte-preserve exactly
            reconstructed.append(block.text)
            continue

        is_valid, violations = validate_narrative_text(block.text, language=language)
        if is_valid:
            reconstructed.append(block.text)
        else:
            all_violations.extend(violations)
            # Attempt single bounded repair
            if repair_fn is not None:
                try:
                    repaired_block = repair_fn(block.text, violations)
                except Exception:
                    repaired_block = repair_narrative_prose(block.text, language=language)
            else:
                repaired_block = repair_narrative_prose(block.text, language=language)

            # Revalidate repaired narrative block
            re_valid, re_violations = validate_narrative_text(repaired_block, language=language)
            if re_valid:
                reconstructed.append(repaired_block)
                any_repaired = True
            else:
                # Controlled safe fallback for this narrative block
                fallback_msg = "Hund har slutfört åtgärden." if language.startswith("sv") else "Hund has completed the action."
                reconstructed.append(fallback_msg)
                fallback_needed = True

    final_text = "".join(reconstructed) if blocks else full_response
    res = NarrativeValidationResult(
        is_valid=len(all_violations) == 0,
        violations=tuple(all_violations),
        repaired_text=final_text if (any_repaired or fallback_needed) else None,
        fallback_used=fallback_needed,
    )
    return final_text, res
