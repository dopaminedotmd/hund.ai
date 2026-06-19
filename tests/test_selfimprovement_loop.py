"""Fas 9.6 — self-improvement-loopen stängs: approve --apply → skill-fil.

Verifierar:
  - build_skill_from_proposal bygger giltig Skill ur approved proposal
  - change_type=core tvingas runtime_policy (TCB röras ej)
  - saknade forbidden_actions/verification → valideringsfel → apply misslyckas
  - apply_skill_proposal: rundtur skriv → läs → validera
  - approve utan --apply ändrar bara status (ingen fil, ingen skill)
  - status "applied" accepteras; ogiltig status refuseras
"""
from __future__ import annotations

import json

import pytest

from hund_cli.selfimprovement import proposal as P
from hund_cli.skills.model import Skill
from hund_cli.skills.validator import validate


# ------------------------------------------------------------------ #
# helpers                                                            #
# ------------------------------------------------------------------ #

def _skill_summary(**over) -> dict:
    base = {
        "title": "loop-skill",
        "problem": "när tester fallerar saknas ett svarsmönster",
        "proposed_change": "använd systematisk felsökning före nästa körning",
        "change_type": "skill",
        "risk": "low",
        "rollback_note": "radera brain/skills/<name>.json",
        "skill_name": "my-loop-skill",
        "skill_domain": "software-development",
        "skill_triggers": ["pytest", "test failed"],
        "skill_steps": ["läs fellögen", "isolera orsak", "fixa"],
        "skill_forbidden": ["delete", "push", "modify_tcb"],
        "skill_verification": ["uv run pytest -q grönt"],
        "skill_required_tools": ["read_file"],
        "skill_when_to_use": "när ett test fallerar",
    }
    base.update(over)
    return base


def _proposal(summary: dict) -> P.Proposal:
    return P.build_from_gaps([], summary)


# ------------------------------------------------------------------ #
# build_skill_from_proposal                                          #
# ------------------------------------------------------------------ #

def test_build_skill_from_proposal():
    """change_type=skill + komplett raw_summary → giltig Skill."""
    p = _proposal(_skill_summary())
    skill = P.build_skill_from_proposal(p, _skill_summary())
    assert skill is not None
    assert isinstance(skill, Skill)
    assert skill.name == "my-loop-skill"
    assert skill.domain == "software-development"
    assert skill.forbidden_actions == ("delete", "push", "modify_tcb")
    assert skill.steps == ("läs fellögen", "isolera orsak", "fixa")
    # mänskligt godkänd → active
    assert skill.status == "active"
    assert validate(skill) == []


def test_build_skill_non_skill_returns_none():
    """change_type != skill → None."""
    p = _proposal({**_skill_summary(), "change_type": "runtime_policy"})
    assert P.build_skill_from_proposal(p, _skill_summary()) is None


def test_build_skill_missing_name_returns_none():
    """saknad skill_name → None."""
    p = _proposal(_skill_summary())
    raw = _skill_summary()
    del raw["skill_name"]
    assert P.build_skill_from_proposal(p, raw) is None


def test_core_change_type_forced_to_runtime_policy():
    """TCB får aldrig röras: change_type=core → runtime_policy, apply ger None."""
    p = P.build_from_gaps([], {"change_type": "core"})
    assert p.change_type == "runtime_policy"
    assert P.build_skill_from_proposal(p, {"skill_name": "x"}) is None


# ------------------------------------------------------------------ #
# validering vid create                                              #
# ------------------------------------------------------------------ #

def test_skill_validation_on_create_missing_forbidden():
    """skill utan forbidden_actions → validate() klagar + apply misslyckas."""
    raw = _skill_summary()
    del raw["skill_forbidden"]
    p = _proposal(_skill_summary())
    skill = P.build_skill_from_proposal(p, raw)
    assert skill is not None
    errors = validate(skill)
    assert any("forbidden_actions" in e for e in errors)
    ok, msg = P.apply_skill_proposal(p, raw)
    assert ok is False
    assert "forbidden_actions" in msg


def test_skill_validation_on_create_missing_verification():
    """skill utan verification → apply misslyckas."""
    raw = _skill_summary()
    del raw["skill_verification"]
    p = _proposal(_skill_summary())
    ok, msg = P.apply_skill_proposal(p, raw)
    assert ok is False
    assert "verification" in msg


# ------------------------------------------------------------------ #
# apply — rundtur (skriv → läs → validera)                          #
# ------------------------------------------------------------------ #

def test_apply_skill_roundtrip(tmp_path, monkeypatch):
    """apply skriver giltig fil, rundtur läses tillbaka och validerar."""
    monkeypatch.setattr(
        "hund_cli.paths.brain_skills_dir", lambda: tmp_path, raising=True
    )
    summary = _skill_summary(skill_name="round-trip-skill")
    p = _proposal(summary)
    ok, msg = P.apply_skill_proposal(p, summary)
    assert ok is True
    written = tmp_path / "round-trip-skill.json"
    assert str(written) == msg
    assert written.exists()
    # rundtur: filen går att ladda som giltig Skill
    reread = Skill.from_dict(json.loads(written.read_text(encoding="utf-8")))
    assert validate(reread) == []
    assert reread.name == "round-trip-skill"


def test_apply_non_skill_proposal_returns_false(tmp_path, monkeypatch):
    """apply på runtime_policy-proposal → (False, ...), ingen fil."""
    monkeypatch.setattr(
        "hund_cli.paths.brain_skills_dir", lambda: tmp_path, raising=True
    )
    p = _proposal({**_skill_summary(), "change_type": "runtime_policy"})
    ok, msg = P.apply_skill_proposal(p, _skill_summary())
    assert ok is False
    assert not list(tmp_path.glob("*.json"))


# ------------------------------------------------------------------ #
# approve utan --apply — status bara                                 #
# ------------------------------------------------------------------ #

def test_approve_without_apply_only_sets_status(tmp_path, monkeypatch):
    """utan --apply: status approved, ingen skill-fil, ingen applied."""
    monkeypatch.setattr(
        "hund_cli.paths.brain_skills_dir", lambda: tmp_path, raising=True
    )
    p = _proposal(_skill_summary())
    P.create(p)
    n = P.set_status(p.id[:8], "approved")
    assert n == 1
    fetched = P.get(p.id[:8])
    assert fetched.status == "approved"
    assert fetched.change_type == "skill"
    # ingen fil skapad (approve utan --apply applicerar ej)
    assert not list(tmp_path.glob("*.json"))


# ------------------------------------------------------------------ #
# status "applied" + ogiltig status                                  #
# ------------------------------------------------------------------ #

def test_set_status_accepts_applied():
    p = _proposal(_skill_summary())
    P.create(p)
    assert P.set_status(p.id[:8], "applied") == 1
    assert P.get(p.id[:8]).status == "applied"


def test_set_status_rejects_invalid_status():
    p = _proposal(_skill_summary())
    P.create(p)
    assert P.set_status(p.id[:8], "deployed") == 0
    assert P.get(p.id[:8]).status == "proposed"


# ------------------------------------------------------------------ #
# raw_summary persistence                                            #
# ------------------------------------------------------------------ #

def test_raw_summary_persisted_with_skill_fields():
    """build_from_gaps sparar full JSON; create/get rundtur bevarar den."""
    summary = _skill_summary()
    p = _proposal(summary)
    assert p.raw_summary  # ej tom
    P.create(p)
    fetched = P.get(p.id[:8])
    assert fetched.raw_summary
    raw = json.loads(fetched.raw_summary)
    assert raw["skill_name"] == "my-loop-skill"
    assert raw["skill_forbidden"] == ["delete", "push", "modify_tcb"]
    # apply-vägen kan bygga skill från den persisterade raw_summary
    skill = P.build_skill_from_proposal(fetched, raw)
    assert skill is not None and validate(skill) == []
