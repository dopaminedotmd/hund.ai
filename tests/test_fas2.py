"""Fas 2 — self-improvement (I) + mastery (J) enhetstester."""
from __future__ import annotations

from hund_cli.base_stats import compute
from hund_cli.knowledge import store as kstore
from hund_cli.selfimprovement import proposal as P


# ---- I: self-improvement ----
def test_proposal_forces_declarative_change_type():
    """TCB-skydd: LLM som föreslår 'core' tvingas till deklarativ."""
    p = P.build_from_gaps(
        [],
        {"title": "t", "problem": "p", "proposed_change": "c",
         "change_type": "core", "risk": "low", "tests_needed": ""},
    )
    assert p.change_type == "runtime_policy"
    assert p.change_type not in {"core", "engine", "safety", "updater", "redactor"}


def test_proposal_crud_roundtrip():
    p = P.build_from_gaps(
        [], {"title": "T", "problem": "P", "proposed_change": "C",
             "change_type": "skill", "risk": "low", "tests_needed": "T1"},
    )
    P.create(p)
    got = P.get(p.id[:8])
    assert got and got.title == "T"
    assert P.set_status(p.id[:8], "approved") == 1
    assert P.get(p.id[:8]).status == "approved"


# ---- J: knowledge (LFU/MRU) ----
def test_knowledge_lfu_orders_by_frequency():
    d = "testdomain_lfu"
    u1 = kstore.add(d, "trig1", "rule1")
    u2 = kstore.add(d, "trig2", "rule2")
    kstore.bump_usage(u1)  # u1 mer frekvent
    top = kstore.top_k(d, k=5)
    rules = [r for _, r in top]
    assert "rule1" in rules and "rule2" in rules
    assert rules[0] == "rule1"  # LFU: mest frekvent först


def test_base_stats_returns_three_measures():
    s = compute()
    assert set(s.keys()) == {"token_efficiency", "speed", "tool_judgment"}
    for v in s.values():
        assert "level" in v


# ---- J: knowledge injiceras i prompt ----
def test_prompt_builder_injects_knowledge():
    from hund_cli.agent.prompt_builder import build_system_prompt
    from hund_cli.doctor import EnvironmentProfile

    prof = EnvironmentProfile(os="Windows", cpu_count=8, capabilities={"has_git": True})
    prompt = build_system_prompt("P", prof, knowledge=[("trig", "min regel")])
    assert "min regel" in prompt
    assert "Relevant kunskap" in prompt
