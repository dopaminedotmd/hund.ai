"""Tests for Gate A4: Persona and safe self-explanation."""
import pytest

from hund.agent.narrative_validation import (
    validate_narrative_text,
    repair_narrative_prose,
    validate_and_repair_response,
)


class TestPersonaNarrativeRules:
    def test_detect_hunden_as_violation(self):
        narrative = "Hunden har undersökt filerna i repot."
        valid, violations = validate_narrative_text(narrative, language="sv")
        assert not valid
        assert any("hunden" in v for v in violations)

    def test_repair_hunden_to_hund(self):
        narrative = "hunden har undersökt filerna."
        repaired = repair_narrative_prose(narrative, language="sv")
        assert "hunden" not in repaired.lower()
        assert "hund" in repaired.lower()

    def test_detect_persona_mechanics_recitation(self):
        narratives = [
            "Hund talar alltid i tredje person.",
            "Eftersom hund använder tredjepersonsperspektiv...",
            "Hund pratar i tredje person och säger inte jag.",
            "As Hund speaks in third-person perspective...",
        ]
        for n in narratives:
            valid, violations = validate_narrative_text(n, language="sv")
            assert not valid, f"Expected violation for: {n}"
            assert any("persona_mechanics" in v or "third_person" in v for v in violations)

    def test_repair_malformed_user_address(self):
        narrative = "Vill hund att vi startar processen?"
        repaired = repair_narrative_prose(narrative, language="sv")
        assert "Vill du att hund" in repaired

    def test_preserve_persona_words_inside_code_blocks(self):
        response = (
            "Här är instruktionen:\n\n"
            "```text\n"
            "Regel 1: hunden är snäll\n"
            "Regel 2: Hund talar alltid i tredje person\n"
            "```\n\n"
            "hund har visat reglerna."
        )
        final_text, result = validate_and_repair_response(response, language="sv")
        assert "Regel 1: hunden är snäll" in final_text
        assert "Regel 2: Hund talar alltid i tredje person" in final_text
        assert "hund har visat reglerna." in final_text
