"""Deterministic, Unicode-aware language detection for turn-local prompt context."""
from __future__ import annotations

import re
import unicodedata

# Strong Swedish vocabulary and function words
_SWEDISH_WORDS = {
    "och", "det", "att", "i", "en", "jag", "hon", "som", "han", "på",
    "den", "med", "var", "sig", "för", "så", "till", "är", "men", "ett",
    "om", "hade", "de", "av", "icke", "mig", "du", "henne", "då", "sin",
    "nu", "har", "inte", "hans", "honom", "skulle", "hennes", "där", "min",
    "man", "ej", "vid", "kunde", "något", "från", "ut", "när", "efter",
    "upp", "vi", "dem", "vara", "vad", "över", "än", "dig", "kan", "sina",
    "här", "ha", "mot", "alla", "under", "någon", "allt", "mycket", "sedan",
    "ju", "denna", "själv", "detta", "åt", "utan", "däremot", "bli", "ingen",
    "mitt", "hur", "vilken", "vilka", "vilket", "dator", "datorn", "minne",
    "minnet", "hårdvara", "hårdvaran", "berätta", "visa", "kör", "skapa",
    "fil", "filen", "funktion", "funktionen", "ändra", "fixa", "kolla",
    "processor", "processorn", "grafikkort", "grafikkortet", "lagring",
}

# Strong English vocabulary and function words
_ENGLISH_WORDS = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
    "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
    "or", "an", "will", "my", "one", "all", "would", "there", "their", "what",
    "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
    "when", "make", "can", "like", "time", "no", "just", "him", "know", "take",
    "people", "into", "year", "your", "good", "some", "could", "them", "see", "other",
    "than", "then", "now", "look", "only", "come", "its", "over", "think", "also",
    "tell", "show", "computer", "hardware", "system", "memory", "storage", "disk",
    "specs", "processor", "recommend", "explain", "create", "write", "modify",
}

# Language-neutral terms that should not skew detection
_NEUTRAL_TERMS = {
    "cpu", "gpu", "ram", "vram", "os", "pc", "llm", "api", "url", "http", "https",
    "python", "powershell", "git", "uv", "node", "docker", "wsl", "windows", "linux",
    "deepseek", "openai", "openrouter", "groq", "anthropic", "claude", "llama",
    "qwen", "mistral", "gemma", "phi", "gpt", "cli", "tui", "id", "gb", "mb",
    "gib", "mib", "tb", "hz", "ghz",
}


def detect_language(text: str) -> str:
    """Detect whether user text is Swedish ('sv') or English ('en').

    Invariants:
    - Unicode-aware casefolding (handles å, ä, ö, Å, Ä, Ö seamlessly).
    - Distinctive Swedish characters (å, ä, ö) strongly bias toward 'sv'.
    - Neutral terms (technical IDs, acronyms, model names) are ignored.
    - Conservative default is 'en' if scoring is tied or text is purely technical.
    """
    if not text or not text.strip():
        return "en"

    # Normalize unicode to NFC and casefold
    normalized = unicodedata.normalize("NFC", text).casefold()

    # Direct check for Swedish unique characters
    has_swedish_chars = any(c in normalized for c in ("å", "ä", "ö"))

    # Tokenize into words
    tokens = re.findall(r"\b[^\W\d_]+\b", normalized, re.UNICODE)
    if not tokens:
        return "sv" if has_swedish_chars else "en"

    sv_score = 3 if has_swedish_chars else 0
    en_score = 0

    for token in tokens:
        if token in _NEUTRAL_TERMS:
            continue
        if token in _SWEDISH_WORDS:
            sv_score += 1
        if token in _ENGLISH_WORDS:
            en_score += 1

    if sv_score > en_score:
        return "sv"
    return "en"
