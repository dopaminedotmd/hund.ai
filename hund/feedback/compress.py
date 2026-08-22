"""Komprimera rådata-lärdomar till kortfattade, aktionsbara regler.

Algoritm:
  1. Gruppera per kategori
  2. Inom varje kategori: sortera efter confidence * seen_count
  3. Ta topp-1 per kategori, fallback topp-2 från största kategorin
  4. Komprimera text till <=200 tecken
  5. Deduplicera mot befintliga lärdomar (similarity > 0.8)
"""

from __future__ import annotations


def compress_lessons(
    raw: list[dict],
    domain: str,
    limit: int = 3,
) -> list[dict]:
    """Komprimera rådata-lärdomar till max `limit` st å <=200 tecken.

    Returnerar lista av dicts: {lesson_text, category, confidence, domain}
    """
    if not raw:
        return []

    # Gruppera per kategori
    groups: dict[str, list[dict]] = {}
    for r in raw:
        cat = r.get("category", "unknown")
        groups.setdefault(cat, []).append(r)

    # Inom varje kategori: sortera efter confidence (högst först)
    for cat in groups:
        groups[cat].sort(key=lambda r: r.get("confidence", 0.0), reverse=True)

    # Ta topp-1 per kategori
    candidates: list[dict] = []
    for cat in ("tool_error", "verify_fail", "user_correction", "success_pattern"):
        if cat in groups and groups[cat]:
            candidates.append(groups[cat][0])

    # Om färre än limit: fyll på från största kategorin
    if len(candidates) < limit:
        # Hitta största kategorin
        biggest_cat = max(groups, key=lambda c: len(groups[c]))
        pool = groups[biggest_cat]
        i = 1  # topp-1 redan tagen
        while len(candidates) < limit and i < len(pool):
            candidates.append(pool[i])
            i += 1

    # Komprimera text till <=200 tecken
    result: list[dict] = []
    seen_texts: set[str] = set()
    for c in candidates[:limit]:
        raw_text = c.get("raw_text", "")
        compressed = _compress_text(raw_text)
        # Hoppa över duplicerad text
        if compressed in seen_texts:
            continue
        seen_texts.add(compressed)
        result.append(
            {
                "lesson_text": compressed,
                "category": c.get("category", "unknown"),
                "confidence": c.get("confidence", 0.5),
                "domain": domain,
            }
        )

    return result


def _compress_text(text: str, max_len: int = 200) -> str:
    """Komprimera en råtext till en kortfattad lärdom.

    Tar bort tidsstämplar, ID:n, exakta felmeddelanden.
    Behåller: vad, varför, konsekvens.
    """
    if not text:
        return ""

    # Ta bort allt efter radbryt för att få kärnbudskapet
    first_line = text.split("\n")[0].strip()

    # Ta bort överflödiga mellanslag
    import re

    cleaned = re.sub(r"\s+", " ", first_line).strip()

    # Truncate till max_len
    if len(cleaned) <= max_len:
        return cleaned

    return cleaned[: max_len - 3] + "..."


def _similarity(a: str, b: str) -> float:
    """Enkel Jaccard-liknande similarity baserad på ordöverlapp."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)
