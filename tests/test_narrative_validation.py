"""Tests for provider-independent narrative validation and protected artifact preservation."""
import pytest

from hund.agent.narrative_validation import (
    extract_content_blocks,
    repair_narrative_prose,
    validate_and_repair_response,
    validate_narrative_text,
)


def test_narrative_validation_detects_swedish_first_person():
    valid, violations = validate_narrative_text("Hund ser att filen finns och föreslår en ändring.", language="sv")
    assert valid is True
    assert len(violations) == 0

    invalid, violations_bad = validate_narrative_text("Jag tycker att vi ska ändra min fil.", language="sv")
    assert invalid is False
    assert any("swedish_first_person" in v for v in violations_bad)


def test_narrative_validation_detects_emojis_and_protocol():
    invalid_emoji, v_emoji = validate_narrative_text("Hund är klar! 🚀🎉", language="sv")
    assert invalid_emoji is False
    assert "emoji_present" in v_emoji

    invalid_proto, v_proto = validate_narrative_text("Hund svarar <|im_start|> system", language="sv")
    assert invalid_proto is False
    assert "raw_protocol_leakage" in v_proto


def test_code_blocks_byte_preserved_with_first_person_and_emojis():
    # Response containing narrative + code block containing 'jag' and emojis
    response = """Hund har uppdaterat funktionen.

```python
def test_user_query():
    # Jag testar detta med emojis 🎉
    message = "min fil och mitt test"
    return message
```

Hund verifierar att koden kompilerar."""

    final_text, res = validate_and_repair_response(response, language="sv")
    assert res.is_valid is True  # Narrative is clean
    # Code block must be 100% untouched
    assert 'def test_user_query():' in final_text
    assert '# Jag testar detta med emojis 🎉' in final_text
    assert '"min fil och mitt test"' in final_text


def test_bounded_repair_narrative_slip():
    # Slips in narrative: "Jag har hittat filen 😊"
    bad_response = "Jag har hittat filen 😊 och jag föreslår att vi kör den."
    final_text, res = validate_and_repair_response(bad_response, language="sv")

    assert res.is_valid is False  # Original had violations
    # Repaired narrative must be third person and emoji-free
    assert "hund har hittat filen" in final_text
    assert "hund föreslår" in final_text
    assert "😊" not in final_text
    assert "jag" not in final_text.lower()


def test_blockquotes_preserved():
    response = """Hund noterade användarens kommentar:

> Jag vill att vi behåller min gamla version 👍

Hund arbetar vidare med uppgiften."""

    final_text, res = validate_and_repair_response(response, language="sv")
    assert "> Jag vill att vi behåller min gamla version 👍" in final_text


def test_inline_code_and_file_paths_are_byte_preserved():
    response = (
        "Hund hittade `Jag/min 🚀` i "
        r"C:\Jag\min-fil🚀.txt och hund lämnar artefakterna oförändrade."
    )

    final_text, _ = validate_and_repair_response(response, language="sv")

    assert "`Jag/min 🚀`" in final_text
    assert r"C:\Jag\min-fil🚀.txt" in final_text
