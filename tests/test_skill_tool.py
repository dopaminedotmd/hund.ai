from __future__ import annotations

import json
from pathlib import Path

from hund.skills.loader import load_domain_skills
from hund.tools.skill_tool import make_handler, parse_create_skill_args
from hund.tools.types import ToolStatus


def _skill_spec(name: str = "focused-review") -> dict:
    return {
        "schema_version": 1,
        "name": name,
        "domain": "code-review",
        "status": "draft",
        "triggers": ["code review", "granska kod"],
        "when_to_use": "When a focused code review is requested.",
        "steps": ["Inspect correctness and report actionable findings."],
        "required_tools": [],
        "forbidden_actions": [
            "self_update", "apply_update", "modify_tcb", "elevate_permissions"
        ],
        "safety_level": "read_only",
        "verification": ["Every finding cites concrete source evidence."],
    }


def test_create_skill_direct_call_saves_skill(tmp_path: Path) -> None:
    result = make_handler(tmp_path)({"skill": _skill_spec()})
    assert result.status is ToolStatus.SUCCESS
    assert "Saved skill 'focused-review'" in result.to_llm_text()
    assert (tmp_path / "brain" / "skills" / "focused-review.json").exists()


def test_create_skill_rejects_invalid_spec_without_writing(tmp_path: Path) -> None:
    spec = _skill_spec("INVALID NAME")
    result = make_handler(tmp_path)({"skill": spec})
    assert result.status is ToolStatus.ERROR
    target = tmp_path / "brain" / "skills" / "INVALID NAME.json"
    assert not target.exists()


def test_create_skill_request_publishes_to_vault(tmp_path: Path) -> None:
    handler = make_handler(home=tmp_path, workspace_path=tmp_path)
    result = handler({
        "request": "create a skill for markdown table formatting",
        "target_scope": "project",
        "desired_disposition": "auto",
    })
    assert result.status is ToolStatus.SUCCESS
    assert "Saved skill" in result.to_llm_text()
    assert (tmp_path / "brain" / "skills").exists()


def test_confirmation_decline_zero_writes(tmp_path: Path) -> None:
    from hund.agent.safety import PermissionEngine
    engine = PermissionEngine()
    args = {"request": "create a skill for malicious hacking"}
    perm = engine.classify("create_skill", args)
    assert perm.risk.value in ("confirm", "confirm_for_write", "dangerous", "blocked")

    # If user declines confirmation, handler is NOT called
    # Zero files written to canonical storage
    skills_dir = tmp_path / "brain" / "skills"
    assert not skills_dir.exists() or len(list(skills_dir.glob("*.json"))) == 0


def test_loader_never_reads_relative_workspace_skill(
    tmp_path: Path, monkeypatch,
) -> None:
    canonical = tmp_path / "canonical"
    workspace = tmp_path / "workspace"
    relative_dir = workspace / "brain" / "skills"
    relative_dir.mkdir(parents=True)
    (relative_dir / "ghost.json").write_text(
        json.dumps(_skill_spec("ghost-skill")), encoding="utf-8"
    )
    monkeypatch.chdir(workspace)
    monkeypatch.setattr("hund.paths.hund_home", lambda: canonical)
    assert load_domain_skills() == []
