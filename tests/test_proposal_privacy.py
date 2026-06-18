"""Proposal privacy — proposals får inte bära råa secrets."""
from __future__ import annotations

from hund_cli.selfimprovement import proposal as P


def test_build_from_gaps_redacts_llm_summary_fields():
    secret = "s" + "k-" + ("c" * 32)
    p = P.build_from_gaps(
        [],
        {
            "title": "leak",
            "problem": f"provider failed with {secret}",
            "proposed_change": f"store token {secret}",
            "change_type": "skill",
            "risk": "low",
            "tests_needed": f"verify {secret}",
        },
    )
    rendered = p.as_markdown()
    assert secret not in p.problem
    assert secret not in p.proposed_change
    assert secret not in p.tests_needed
    assert secret not in rendered
    assert "[REDACTED:secret]" in rendered
