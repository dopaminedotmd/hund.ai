from __future__ import annotations

import json
from pathlib import Path

from hund.skills.loader import load_domain_skills
from hund.tools.skill_tool import make_handler
from hund.tools.types import ToolStatus


def _skill_spec(name: str = "focused-review") -> dict:
    return {
        "schema_version": 1,
        "name": name,
        "domain": "code-review",
        "status": "active",
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


def test_create_skill_uses_canonical_home_and_forces_draft(tmp_path: Path) -> None:
    result = make_handler(tmp_path)({"skill": _skill_spec()})
    assert result.status is ToolStatus.SUCCESS
    target = tmp_path / "brain" / "skills" / "focused-review.json"
    assert target.exists()
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored["lifecycle_state"] == "draft"
    assert stored["vault_state"] == "vaulted"


def test_create_skill_rejects_invalid_spec_without_writing(tmp_path: Path) -> None:
    spec = _skill_spec("INVALID NAME")
    result = make_handler(tmp_path)({"skill": spec})
    assert result.status is ToolStatus.ERROR
    assert not (tmp_path / "brain" / "skills").exists()


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
