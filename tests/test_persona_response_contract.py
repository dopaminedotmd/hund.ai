"""Regression tests for aligned runtime and canonical response contracts."""
from pathlib import Path

from hund.agent.response_policy import get_response_policy_rules
from hund.persona import get_compact_voice_contract


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_contract_has_adaptive_completeness_and_no_signoff_rule():
    contract = get_compact_voice_contract()
    assert "så kort som möjligt och så komplett som nödvändigt" in contract.lower()
    assert "be inte användaren om en uppgift" in contract.lower()
    assert "1–4" not in contract
    assert "1-4" not in contract
    assert len(contract) <= 1500


def test_policy_languages_have_same_semantics_without_fixed_line_limit():
    swedish = "\n".join(get_response_policy_rules(language="sv"))
    english = "\n".join(get_response_policy_rules(language="en"))
    assert "så kort som möjligt och så komplett som nödvändigt" in swedish.lower()
    assert "as short as possible and as complete as necessary" in english.lower()
    assert "be användaren om en uppgift" in swedish.lower()
    assert "ask the user for a task" in english.lower()
    assert "1-4" not in swedish + english
    assert "1–4" not in swedish + english


def test_canonical_persona_and_bible_share_response_truth():
    canonical = (ROOT / "hund/assets/hund-system/hund.md").read_text(encoding="utf-8")
    bible = (ROOT / "HUND_COMPLETE_BIBLE.md").read_text(encoding="utf-8")
    for document in (canonical, bible):
        lowered = document.lower()
        assert "as short as possible and as complete as necessary" in lowered
        assert "do not ask the user for a task" in lowered
        assert "1–4" not in document
        assert "1-4" not in document
        assert "state direction" not in lowered
