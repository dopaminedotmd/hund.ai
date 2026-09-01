"""RED/GREEN tests for structured narrative clause repair (R1)."""
import pytest

from hund.agent.narrative_validation import (
    repair_narrative_prose,
    validate_and_repair_response,
    validate_narrative_text,
)


def test_detect_persona_mechanics_recitation():
    """Detection regex detects third-person recitation patterns."""
    samples = [
        "hund pratar i tredje person, håller svaren korta.",
        "hund talar alltid i tredje person, och hjälper dig gärna.",
        "Hund svarar i tredje person. Här är resultatet.",
        "hund pratar i tredje person och håller svaren korta.",
        "Hund speaks in third person, keeping answers concise.",
        "As hund speaks in third-person perspective, answers are concise.",
        "hund pratar i tredje person.",
    ]
    for s in samples:
        valid, violations = validate_narrative_text(s, language="sv")
        assert not valid, f"Expected violation for: {s}"
        assert any("persona_mechanics" in v for v in violations)


def test_repair_pratar_i_tredje_person_comma_clause():
    """Clause repair removes entire offending clause without leaving broken prepositions."""
    input_text = "hund pratar i tredje person, håller svaren korta när det räcker."
    repaired = repair_narrative_prose(input_text, language="sv")
    assert repaired == "hund håller svaren korta när det räcker."
    assert "hund pratar i" not in repaired
    assert "tredje person" not in repaired


def test_repair_talar_i_tredje_person_and_clause():
    """Clause repair handles 'talar i tredje person och' cleanly."""
    input_text = "hund talar alltid i tredje person och håller svaren korta."
    repaired = repair_narrative_prose(input_text, language="sv")
    assert repaired == "hund håller svaren korta."
    assert "tredje person" not in repaired


def test_repair_standalone_tredje_person_sentence():
    """Clause repair removes standalone third person sentence cleanly."""
    input_text = "Hund svarar i tredje person. Här är din fil."
    repaired = repair_narrative_prose(input_text, language="sv")
    assert repaired == "Här är din fil."
    assert "tredje person" not in repaired


def test_repair_english_third_person_clause():
    """Clause repair removes English third person recitation grammatically."""
    input_text = "Hund speaks in third person, keeping answers concise."
    repaired = repair_narrative_prose(input_text, language="en")
    assert "third person" not in repaired.lower()
    assert "speaks in" not in repaired.lower()
    assert repaired == "Hund keeps answers concise." or repaired == "Hund keeping answers concise." or "concise" in repaired


def test_repair_does_not_break_ordinary_third_word():
    """Ordinary words like 'tredje delen' or 'tredje försöket' are not damaged unless persona recitation."""
    input_text = "hund kör nu det tredje försöket på uppgiften."
    valid, violations = validate_narrative_text(input_text, language="sv")
    assert valid, f"Unexpected violation: {violations}"
    repaired = repair_narrative_prose(input_text, language="sv")
    assert repaired == "hund kör nu det tredje försöket på uppgiften."


def test_repair_em_dash_separator_clause():
    """Clause repair handles em-dash and en-dash separators cleanly without leaving trailing verbs."""
    input_text = "Hund talar i tredje person — håller sig kortfattad och arbetar metodiskt."
    repaired = repair_narrative_prose(input_text, language="sv")
    assert repaired in (
        "hund håller sig kortfattad och arbetar metodiskt.",
        "Hund håller sig kortfattad och arbetar metodiskt.",
    )
    assert "talar" not in repaired
    assert "—" not in repaired


def test_repair_comma_and_clause_no_stray_and():
    """Clause repair handles 'tredje person, och' without leaving a stray 'och'."""
    input_text = "Hund talar i tredje person, och håller sig kortfattad."
    repaired = repair_narrative_prose(input_text, language="sv")
    assert repaired in (
        "hund håller sig kortfattad.",
        "Hund håller sig kortfattad.",
    )
    assert "hund och" not in repaired.lower()


def test_repair_missing_i_tredje_person_clause():
    """Clause repair handles 'talar tredje person' without preposition 'i'."""
    input_text = "hund talar tredje person, är precis med ord och aldrig osäker på vad som är verifierat"
    valid, violations = validate_narrative_text(input_text, language="sv")
    assert not valid
    repaired = repair_narrative_prose(input_text, language="sv")
    assert repaired in (
        "hund är precis med ord och aldrig osäker på vad som är verifierat",
        "Hund är precis med ord och aldrig osäker på vad som är verifierat",
    )
    assert "tredje person" not in repaired
    assert "talar" not in repaired

