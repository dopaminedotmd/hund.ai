"""Skill-system v1 — validator, loader, matcher."""
from __future__ import annotations

import json
from pathlib import Path

from hund.skills.loader import (
    add_skill,
    get_skill,
    load_file,
    load_skills,
    skills_dir,
)
from hund.skills.matcher import match, summaries
from hund.skills.model import Skill
from hund.skills.validator import validate


def _valid_skill(**over) -> Skill:
    base = dict(
        schema_version=1,
        name="x-skill",
        domain="software-development",
        status="active",
        triggers=("pytest",),
        when_to_use="när X",
        steps=("steg 1",),
        required_tools=("read_file",),
        forbidden_actions=("delete", "self_update", "apply_update", "modify_tcb", "elevate_permissions"),
        safety_level="confirm_for_write",
        verification=("uv run pytest",),
    )
    base.update(over)
    return Skill(**base)


def test_builtin_loads_and_validates():
    skills = load_skills()
    names = {s.name for s in skills}
    assert "python-project-inspection" in names
    assert all(validate(s) == [] for s in skills)


def test_get_skill_by_name():
    assert get_skill("python-project-inspection") is not None
    assert get_skill("does-not-exist") is None


def test_match_returns_max_top3_and_only_active(tmp_path):
    # bygg 4 aktiva + 1 disabled, alla matchar trigger "pytest"
    skills = [
        _valid_skill(name=f"sk{i}", triggers=("pytest",), status="active")
        for i in range(4)
    ]
    skills.append(_valid_skill(name="dis", triggers=("pytest",), status="disabled"))
    hits = match(skills, "kör pytest snälla")
    assert len(hits) == 3
    assert all(h.status == "active" for h in hits)
    assert "dis" not in {h.name for h in hits}


def test_match_scores_higher_trigger_count_first():
    a = _valid_skill(name="a", triggers=("pytest",))
    b = _valid_skill(name="b", triggers=("pytest", "pyproject.toml"))
    hits = match([a, b], "kör pytest och läs pyproject.toml")
    assert hits[0].name == "b"


def test_invalid_skill_missing_verification_fails():
    bad = _valid_skill(verification=())
    assert any("verification" in e for e in validate(bad))


def test_invalid_skill_missing_forbidden_actions_fails():
    bad = _valid_skill(forbidden_actions=())
    assert any("forbidden_actions" in e for e in validate(bad))


def test_invalid_skill_requiring_banned_tool_fails():
    bad = _valid_skill(required_tools=("self_update",))
    assert any("self_update" in e for e in validate(bad))


def test_invalid_safety_level_fails():
    bad = _valid_skill(safety_level="yolo")
    assert any("safety_level" in e for e in validate(bad))


def test_invalid_name_fails():
    bad = _valid_skill(name="Bad Name!")
    assert any("name" in e for e in validate(bad))


def test_add_skill_writes_valid_file_to_hundhome(tmp_path):
    src = tmp_path / "src.json"
    src.write_text(
        json.dumps(_valid_skill(name="custom-1").to_dict()), encoding="utf-8"
    )
    skill, errors = add_skill(src, home=tmp_path)
    assert errors == []
    assert skill is not None
    assert (skills_dir(home=tmp_path) / "custom-1.json").exists()
    assert get_skill("custom-1", home=tmp_path) is not None


def test_add_skill_rejects_invalid(tmp_path):
    src = tmp_path / "bad.json"
    src.write_text(
        json.dumps(_valid_skill(verification=()).to_dict()), encoding="utf-8"
    )
    skill, errors = add_skill(src, home=tmp_path)
    assert skill is None
    assert errors
    assert not (skills_dir(home=tmp_path) / "x-skill.json").exists()


def test_load_file_invalid_json_returns_errors(tmp_path):
    bad = tmp_path / "p.json"
    bad.write_text("{ broken", encoding="utf-8")
    skill, errors = load_file(bad)
    assert skill is None
    assert errors


def test_user_skill_shadows_builtin_by_name(tmp_path):
    # skriv en python-project-inspection.json i HundHome med annan when_to_use
    override = _valid_skill(
        name="python-project-inspection",
        when_to_use="OVERIDDEN av användare",
    )
    skills_dir(home=tmp_path).mkdir(parents=True)
    (skills_dir(home=tmp_path) / "python-project-inspection.json").write_text(
        json.dumps(override.to_dict()), encoding="utf-8"
    )
    loaded = load_skills(home=tmp_path)
    # namnunik (ej duplicerad)
    assert sum(1 for s in loaded if s.name == "python-project-inspection") == 1
    assert get_skill("python-project-inspection", home=tmp_path).when_to_use == "OVERIDDEN av användare"


def test_summaries_returns_compact_lines():
    skills = [_valid_skill(name="s1", triggers=("pytest",))]
    lines = summaries(skills, "kör pytest")
    assert lines == ["[s1] (software-development) när X"]
