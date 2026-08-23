"""Phrase table (data) for Hund thinking model: gerund (present) <-> past tense.

Pure function select_thinking_phrase(user) maps user intent to (gerund, past).
All phrases are in English without emojis.
"""
from __future__ import annotations

DEFAULT_PHRASE: tuple[str, str | None] = ("hund is thinking", "hund thought it through.")
READ_PHRASE: tuple[str, str | None] = ("hund is reading your message", None)

# Keyword mappings -> (gerund, past). Longest keyword match wins.
_INTENT_ENTRIES: list[tuple[tuple[str, ...], tuple[str, str | None]]] = [
    (
        ("who are you", "who-are-you", "identify", "vem är du", "vad är du"),
        ("hund is recalling", "hund recalled."),
    ),
    (
        (
            "system specs",
            "hardware specs",
            "specs",
            "cpu",
            "gpu",
            "ram",
            "system",
            "hardware",
            "specifikationer",
        ),
        ("hund is checking your system", "hund checked."),
    ),
    (
        ("fix", "bug", "error", "crash", "debug", "traceback", "exception", "laga", "bugg"),
        ("hund is inspecting the code", "hund inspected."),
    ),
    (
        ("write", "create", "build", "make", "skapa", "bygg", "skriv"),
        ("hund is planning the build", "hund planned."),
    ),
    (
        ("search", "find", "where", "sök", "hitta", "var finns"),
        ("hund is searching", "hund searched."),
    ),
    (
        ("test", "verify", "verifiera", "testa", "pytest"),
        ("hund is verifying", "hund verified."),
    ),
    (
        ("refactor", "clean", "optimize", "refaktorera", "optimera", "städa"),
        ("hund is optimizing", "hund optimized."),
    ),
    (
        ("read", "läs"),
        ("hund is reading", None),
    ),
]

# Flattened and sorted by keyword length descending (longest keyword match wins)
_KEYWORD_PAIRS: list[tuple[str, tuple[str, str | None]]] = sorted(
    [
        (kw.lower(), pair)
        for keywords, pair in _INTENT_ENTRIES
        for kw in keywords
    ],
    key=lambda item: len(item[0]),
    reverse=True,
)


def select_thinking_phrase(user: str) -> tuple[str, str | None]:
    """Select the appropriate (gerund, past) thinking phrase tuple for user input.

    - Longest keyword match wins (e.g. 'system specs' matches before 'system').
    - Returns (gerund, past).
    - If no keyword matches, falls back to DEFAULT_PHRASE.
    """
    if not user:
        return DEFAULT_PHRASE
    u = user.lower()
    for kw, pair in _KEYWORD_PAIRS:
        if kw in u:
            return pair
    return DEFAULT_PHRASE
