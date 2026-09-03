from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from hund.skills.authoring import (
    AuthoringState,
    SkillAuthoringIntent,
    SkillDraft,
    authorize_publication,
    create_authoring_session,
    get_authoring_registry,
    transition_session,
)
from hund.skills.contracts import compute_payload_hash
from hund.skills.loader import load_domain_skills
from hund.skills.model import BANNED_ACTIONS, Skill
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
        "forbidden_actions": sorted(list(BANNED_ACTIONS)),
        "safety_level": "read_only",
        "verification": ["Every finding cites concrete source evidence."],
        "version": "1.0.0",
        "capability_id": f"code-review/{name}",
        "scope": "global",
    }


def test_create_skill_authorized_call_saves_skill(tmp_path: Path) -> None:
    reg = get_authoring_registry()
    reg.clear()

    spec = _skill_spec("focused-review")
    skill = Skill.from_dict(spec)
    draft = SkillDraft(action="CREATE", skill=skill)

    intent = SkillAuthoringIntent(
        operation="create",
        capability="code review",
        target_scope="global",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt="create code review skill",
    )
    session = create_authoring_session(intent, session_id="tool-test-1", registry=reg)
    session = transition_session(session, AuthoringState.BUILDING, registry=reg)
    session = transition_session(session, AuthoringState.QUALITY_CHECKING, draft=draft, registry=reg)
    session = transition_session(session, AuthoringState.READY, registry=reg)
    session, auth = authorize_publication(session, disposition="vault", registry=reg)
    session = transition_session(session, AuthoringState.PUBLISHING, registry=reg)
    auth = replace(auth, is_used=True)
    session = replace(session, publication_authorization=auth)
    reg.save(session)

    call_args = {
        "session_id": session.session_id,
        "authorization_id": auth.authorization_id,
        "payload_hash": auth.payload_hash,
        "desired_disposition": "vault",
        "skill": spec,
    }

    result = make_handler(home=tmp_path, workspace_path=tmp_path)(call_args)
    assert result.status is ToolStatus.SUCCESS
    assert "Saved skill 'focused-review'" in result.to_llm_text()
    from hund.skills.vault import SkillVault
    vault = SkillVault(home=tmp_path)
    assert vault.find_skill("focused-review") is not None


def test_create_skill_tokenless_call_rejected(tmp_path: Path) -> None:
    handler = make_handler(home=tmp_path, workspace_path=tmp_path)
    res = handler({"skill": _skill_spec("unauthorized-skill")})
    assert res.status is ToolStatus.ERROR
    assert "authorization" in res.public_error.lower()
    from hund.skills.vault import SkillVault
    assert SkillVault(home=tmp_path).find_skill("unauthorized-skill") is None


def test_create_skill_rejects_invalid_spec_without_writing(tmp_path: Path) -> None:
    spec = _skill_spec("INVALID NAME")
    result = make_handler(tmp_path)({"skill": spec})
    assert result.status is ToolStatus.ERROR
    target = tmp_path / "brain" / "skills" / "INVALID NAME.json"
    assert not target.exists()


def test_confirmation_decline_zero_writes(tmp_path: Path) -> None:
    from hund.agent.safety import PermissionEngine
    engine = PermissionEngine()
    args = {"skill": _skill_spec("malicious-hack")}
    perm = engine.classify("create_skill", args)
    assert perm.risk.value in ("confirm", "confirm_for_write", "dangerous", "blocked")

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
