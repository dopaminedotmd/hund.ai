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


def test_strip_raw_unbalanced_asterisks_swedish_and_english():
    """Golden: final-text without raw unbalanced '**' markers in Swedish and English."""
    # Swedish with leaked prefix marker like **ULäst `README.md`**
    sv_raw = "**ULäst `README.md`** och hund har verifierat ändringarna."
    sv_fixed = repair_narrative_prose(sv_raw, language="sv")
    assert not sv_fixed.startswith("**U")
    assert sv_fixed.count("**") % 2 == 0

    # Swedish with dangling trailing **
    sv_dangling = "Hund har slutfört uppgiften. **"
    sv_dangling_fixed = repair_narrative_prose(sv_dangling, language="sv")
    assert "**" not in sv_dangling_fixed
    assert "Hund har slutfört uppgiften." in sv_dangling_fixed

    # English with unbalanced leading **
    en_raw = "**Hund analyzed the workspace and found 3 errors."
    en_fixed = repair_narrative_prose(en_raw, language="en")
    assert "**" not in en_fixed
    assert "Hund analyzed the workspace" in en_fixed

    # Balanced markdown bold is preserved
    balanced = "Hund uppdaterade **README.md** korrekt."
    assert repair_narrative_prose(balanced, language="sv") == balanced


def test_numeric_conflict_758_vs_833_flagged_and_repaired():
    """758-vs-833 pattern: unacknowledged conflicting numbers are flagged in response."""
    conflict_text = "Ordräkningen gav 758 ord mot 833 ord i sammanställningen."
    final_text, res = validate_and_repair_response(conflict_text, language="sv")

    # Violation should be recorded
    assert any("unresolved_numeric_conflict" in v for v in res.violations)
    # The repaired text must flag the conflict rather than presenting side-by-side quietly
    assert "Konflikt:" in final_text or "avvikelse" in final_text.lower()
    assert "758" in final_text and "833" in final_text


def test_path_contract_in_default_tools_and_consistent_fallback(tmp_path):
    """Fallback text in tool descriptions + identical tool flow across 3 invocations."""
    from hund.tools.default_tools import _PATH_PARAM, register_defaults
    from hund.tools import registry

    # 1. Contract text in _PATH_PARAM and registered tool descriptions
    assert "use the terminal with the user-provided absolute path or request workspace switch" in _PATH_PARAM["description"]

    register_defaults(tmp_path)
    for tool_name in ("read_file", "search_files", "write_file"):
        tool = registry.get(tool_name)
        assert tool is not None
        assert "use the terminal with the user-provided absolute path or request workspace switch" in tool.description

    # 2. Same absolute path outside workspace x3 -> identical result
    outside_file = tmp_path.parent / "external_target.txt"
    read_fn = registry.get("read_file").handler
    res1 = read_fn({"path": str(outside_file)})
    res2 = read_fn({"path": str(outside_file)})
    res3 = read_fn({"path": str(outside_file)})

    assert res1 == res2 == res3
    assert "use the terminal with the user-provided absolute path or request workspace switch" in res1

