"""Runtime Policy v1 — laddning, validering, locked-regler."""
from __future__ import annotations

import json
from pathlib import Path

from hund.policy.defaults import default_policy
from hund.policy.loader import load_file, load_policy, policy_path, validate
from hund.policy.model import Policy, Rule


def test_default_policy_is_valid():
    pol = default_policy()
    assert validate(pol) == []
    assert pol.version == 1
    assert any(r.locked for r in pol.rules)


def test_prompt_rules_only_returns_prompt_scope():
    pol = default_policy()
    texts = pol.prompt_rules()
    assert texts  # minst en
    assert all("instruktioner" in t.lower() or "data" in t.lower() for t in texts)


def test_load_policy_falls_back_to_default_without_local_file(tmp_path):
    pol = load_policy(home=tmp_path)
    assert pol == default_policy()


def test_local_valid_policy_loads(tmp_path):
    pol = default_policy()
    # lägg till en egen, ej låst regel
    local = Policy(
        version=1,
        rules=pol.rules + (Rule("my_rule", "behavior", "gör X först", locked=False),),
        forbidden_core_paths=pol.forbidden_core_paths,
    )
    p = policy_path(home=tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(local.to_dict()), encoding="utf-8")
    loaded = load_policy(home=tmp_path)
    assert loaded.rule("my_rule") is not None


def test_local_policy_missing_locked_rule_is_invalid(tmp_path):
    pol = default_policy()
    kept = tuple(r for r in pol.rules if r.id != "human_gate" or True)  # keep all
    # ta bort en LOCKED regel
    tampered = Policy(
        version=1,
        rules=tuple(r for r in kept if r.id != "tool_output_untrusted"),
        forbidden_core_paths=pol.forbidden_core_paths,
    )
    errs = validate(tampered)
    assert any("tool_output_untrusted" in e for e in errs)


def test_local_policy_unlocking_locked_rule_is_invalid():
    pol = default_policy()
    unlocked = tuple(
        Rule(r.id, r.scope, r.text, locked=False) if r.id == "no_external_exfiltration" else r
        for r in pol.rules
    )
    tampered = Policy(1, unlocked, pol.forbidden_core_paths)
    errs = validate(tampered)
    assert any("no_external_exfiltration" in e for e in errs)


def test_local_policy_changing_locked_rule_text_is_invalid():
    pol = default_policy()
    changed = tuple(
        Rule(r.id, r.scope, "annytt text", r.locked) if r.id == "tcb_immutable" else r
        for r in pol.rules
    )
    tampered = Policy(1, changed, pol.forbidden_core_paths)
    errs = validate(tampered)
    assert any("tcb_immutable" in e for e in errs)


def test_load_file_invalid_json_returns_errors(tmp_path):
    bad = tmp_path / "policy.json"
    bad.write_text("{ not json", encoding="utf-8")
    pol, errs = load_file(bad)
    assert pol is None
    assert errs


def test_to_dict_from_dict_roundtrip():
    pol = default_policy()
    again = Policy.from_dict(pol.to_dict())
    assert again == pol


def test_invalid_scope_is_flagged():
    bad = Policy(
        1,
        (Rule("r1", "weird_scope", "text"),),
        (),
    )
    # weird_scope-regeln saknas bland baseline locked men den får finnas ändå;
    # felen ska nämnas scope-problemet.
    errs = validate(bad)
    assert any("weird_scope" in e for e in errs)


def test_forbidden_core_paths_match_safety_tcb():
    """Invariant: policy.forbidden_core_paths == safety TCB_FILES + TCB_DIRS."""
    from hund.agent.safety import TCB_DIRS, TCB_FILES

    pol = default_policy()
    policy_paths = set(pol.forbidden_core_paths)
    safety_paths = set(TCB_FILES) | set(TCB_DIRS)
    assert policy_paths == safety_paths
