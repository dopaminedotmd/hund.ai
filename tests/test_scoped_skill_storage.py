"""Tests for scoped skill storage, schema v2 migration, atomic fsync, snapshots, rollbacks, and journals."""
from dataclasses import replace
import json
import os
from pathlib import Path
import pytest

from hund.skills.loader import get_skill, load_domain_skills, load_skills
from hund.skills.model import BANNED_ACTIONS, Skill
from hund.skills.scope import compute_workspace_key
from hund.skills.storage import SkillStorage
from hund.skills.vault import SkillVault
from hund.ui.snapshots import collect_skills


def _make_skill(name: str = "storage-skill", scope: str = "global", version: str = "1.0.0") -> Skill:
    return Skill(
        schema_version=1,
        name=name,
        domain="general",
        status="active",
        lifecycle_state="active",
        vault_state="vaulted",
        triggers=("test trigger",),
        when_to_use="When running test.",
        steps=("Step 1: do work",),
        required_tools=(),
        forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
        safety_level="read_only",
        verification=("Verify results.",),
        version=version,
        capability_id=f"general/{name}",
        scope=scope,
        personal_skill_xp=0,
    )


def test_scoped_identity_collision(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    ws_key = compute_workspace_key(tmp_path / "ws1")

    s_global = _make_skill("my-skill", scope="global")
    s_project = _make_skill("my-skill", scope="project")

    p_global = storage.write_canonical_atomic(s_global, workspace_key="global")
    p_project = storage.write_canonical_atomic(s_project, workspace_key=ws_key)

    assert p_global != p_project
    assert p_global.exists()
    assert p_project.exists()


def test_get_skill_scoped_lookup_precedence(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    ws_path = tmp_path / "my_project"
    ws_path.mkdir()
    ws_key = compute_workspace_key(ws_path)

    # 1. Write global skill with custom description
    g_skill = _make_skill("lookup-skill", scope="global", version="1.0.0")
    storage.write_canonical_atomic(g_skill, workspace_key="global")

    # When querying without workspace, returns global
    found_g = get_skill("lookup-skill", home=tmp_path)
    assert found_g is not None
    assert found_g.version == "1.0.0"

    # 2. Write project skill with same name but version 2.0.0
    p_skill = _make_skill("lookup-skill", scope="project", version="2.0.0")
    storage.write_canonical_atomic(p_skill, workspace_key=ws_key)

    # When querying with workspace, project skill shadows global
    found_p = get_skill("lookup-skill", home=tmp_path, workspace=ws_path)
    assert found_p is not None
    assert found_p.version == "2.0.0"

    # Builtin precedence: "file-operations" always returns builtin
    builtin = get_skill("file-operations", home=tmp_path, workspace=ws_path)
    assert builtin is not None
    assert builtin.domain == "constitutional" or "file" in builtin.name


def test_scoped_storage_and_loader_isolation(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    ws_a = tmp_path / "proj_a"
    ws_b = tmp_path / "proj_b"
    ws_a.mkdir()
    ws_b.mkdir()

    key_a = compute_workspace_key(ws_a)
    key_b = compute_workspace_key(ws_b)

    s_a = _make_skill("skill-a", scope="project")
    storage.write_canonical_atomic(s_a, workspace_key=key_a)

    # Loaded in workspace A
    skills_a = load_domain_skills(home=tmp_path, workspace=ws_a)
    assert any(s.name == "skill-a" for s in skills_a)

    # Isolated from workspace B
    skills_b = load_domain_skills(home=tmp_path, workspace=ws_b)
    assert not any(s.name == "skill-a" for s in skills_b)


def test_vault_reads_project_skills_from_workspace_path(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    vault = SkillVault(home=tmp_path)
    workspace = tmp_path / "project"
    workspace.mkdir()
    workspace_key = compute_workspace_key(workspace)
    skill = _make_skill("project-visible", scope="project")

    storage.write_canonical_atomic(skill, workspace_key=workspace_key)
    vault.sync_scoped_state(
        [skill], workspace_key=workspace_key, desired_equip=skill.name
    )

    assert [item.name for item in vault.get_active_skills(workspace=workspace)] == [
        "project-visible"
    ]
    assert [
        item.name
        for item in vault.get_active_skills(workspace_key=workspace_key)
    ] == ["project-visible"]


def test_skills_snapshot_uses_current_workspace_scope(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    vault = SkillVault(home=tmp_path)
    workspace = tmp_path / "project"
    other_workspace = tmp_path / "other-project"
    workspace.mkdir()
    other_workspace.mkdir()
    workspace_key = compute_workspace_key(workspace)
    skill = _make_skill("snapshot-visible", scope="project")

    storage.write_canonical_atomic(skill, workspace_key=workspace_key)
    vault.sync_scoped_state(
        [skill], workspace_key=workspace_key, desired_equip=skill.name
    )

    visible = collect_skills(home=tmp_path, workspace=workspace)
    hidden = collect_skills(home=tmp_path, workspace=other_workspace)

    assert [item.name for item in visible.equipped] == ["snapshot-visible"]
    assert hidden.equipped == ()


def test_loader_ignores_reserved_dirs(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    skill = _make_skill("staged-only")
    storage.save_staged_draft(skill, None, workspace_key="global")
    storage.snapshot_prior_version(skill, workspace_key="global")

    # load_domain_skills should not load draft or snapshot files
    domain_skills = load_domain_skills(home=tmp_path)
    assert not any(s.name == "staged-only" for s in domain_skills)


def test_atomic_write_fsync_windows(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    skill = _make_skill("atomic-test")
    p = storage.write_canonical_atomic(skill)
    assert p.exists()
    assert json.loads(p.read_text(encoding="utf-8"))["name"] == "atomic-test"


def test_journal_compensation_on_failure(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    skill = _make_skill("fail-test")
    canonical_path = storage.write_canonical_atomic(skill)
    assert canonical_path.exists()

    import hashlib
    file_hash = hashlib.sha256(canonical_path.read_bytes()).hexdigest()

    tx = {
        "tx_id": "tx123",
        "action": "CREATE",
        "name": "fail-test",
        "scope_key": "global",
        "intended_canonical_hash": file_hash,
        "phase": "CANONICAL_WRITTEN",
    }
    storage.compensate_journal(tx)
    assert not canonical_path.exists()


def test_startup_crash_recovery_journal(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    # Write interrupted transaction
    tx = {
        "tx_id": "tx_crash",
        "action": "CREATE",
        "name": "crashed-skill",
        "scope_key": "global",
        "phase": "STARTED",
    }
    storage.write_journal_atomic(tx)

    recovered = storage.recover_pending_journals()
    assert len(recovered) > 0
    assert any("tx_crash" in r for r in recovered)


def test_journal_phase_updates_are_atomic(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    tx = {"tx_id": "tx_phase", "phase": "STARTED"}
    j_path = storage.write_journal_atomic(tx)
    assert j_path.exists()

    storage.update_journal_phase("tx_phase", "CANONICAL_WRITTEN")
    updated = json.loads(j_path.read_text(encoding="utf-8"))
    assert updated["phase"] == "CANONICAL_WRITTEN"


def test_corrupt_journal_fails_closed(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    hdir = storage._skills_dir / ".history"
    hdir.mkdir(parents=True, exist_ok=True)
    corrupt_tx = hdir / "tx_corrupt.json"
    corrupt_tx.write_text("{invalid json", encoding="utf-8")

    recovered = storage.recover_pending_journals()
    assert any("quarantined" in r for r in recovered)
    assert not corrupt_tx.exists()


def test_legacy_skill_state_v1_migration(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    s1 = _make_skill("legacy1")
    s2 = _make_skill("legacy2")
    storage.write_canonical_atomic(s1)
    storage.write_canonical_atomic(s2)

    state_file = tmp_path / "brain" / "skill_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"active": ["legacy1"], "vaulted": ["legacy2"]}), encoding="utf-8")

    vault = SkillVault(home=tmp_path)
    new_state = json.loads(state_file.read_text(encoding="utf-8"))
    assert new_state.get("schema_version") == 2
    assert len(new_state.get("entries", [])) == 2


def test_legacy_migration_idempotent_repeated_noop(tmp_path: Path):
    test_legacy_skill_state_v1_migration(tmp_path)
    state_file = tmp_path / "brain" / "skill_state.json"
    mtime1 = state_file.stat().st_mtime_ns

    # Second init on already migrated state
    vault2 = SkillVault(home=tmp_path)
    mtime2 = state_file.stat().st_mtime_ns
    assert mtime1 == mtime2


def test_legacy_migration_unresolved_name_is_not_live(tmp_path: Path):
    state_file = tmp_path / "brain" / "skill_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    # "ghost-skill" has no canonical JSON file
    state_file.write_text(json.dumps({"active": ["ghost-skill"], "vaulted": []}), encoding="utf-8")

    vault = SkillVault(home=tmp_path)
    new_state = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(new_state.get("entries", [])) == 0


def test_legacy_migration_duplicate_name_vaulted(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    s = _make_skill("dup-skill")
    storage.write_canonical_atomic(s)

    state_file = tmp_path / "brain" / "skill_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    # Name appears in both active and vaulted -> fail closed to vaulted
    state_file.write_text(json.dumps({"active": ["dup-skill"], "vaulted": ["dup-skill"]}), encoding="utf-8")

    vault = SkillVault(home=tmp_path)
    new_state = json.loads(state_file.read_text(encoding="utf-8"))
    entry = next(e for e in new_state["entries"] if e["name"] == "dup-skill")
    assert entry["vault_state"] == "vaulted"


def test_legacy_migration_identity_collision_aborts(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    s = _make_skill("ident-collision")
    storage.write_canonical_atomic(s)

    state_file = tmp_path / "brain" / "skill_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"active": ["ident-collision", "ident-collision"], "vaulted": []}), encoding="utf-8")

    vault = SkillVault(home=tmp_path)
    new_state = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(new_state["entries"]) == 1


def test_legacy_migration_preserves_active_vaulted_disposition(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    s_act = _make_skill("act-skill")
    s_vlt = _make_skill("vlt-skill")
    storage.write_canonical_atomic(s_act)
    storage.write_canonical_atomic(s_vlt)

    state_file = tmp_path / "brain" / "skill_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"active": ["act-skill"], "vaulted": ["vlt-skill"]}), encoding="utf-8")

    vault = SkillVault(home=tmp_path)
    new_state = json.loads(state_file.read_text(encoding="utf-8"))
    e_act = next(e for e in new_state["entries"] if e["name"] == "act-skill")
    e_vlt = next(e for e in new_state["entries"] if e["name"] == "vlt-skill")
    assert e_act["vault_state"] == "equipped"
    assert e_vlt["vault_state"] == "vaulted"


def test_legacy_migration_leaves_legacy_files_unmoved(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    s = _make_skill("unmoved-skill")
    p = storage.write_canonical_atomic(s)

    state_file = tmp_path / "brain" / "skill_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"active": ["unmoved-skill"], "vaulted": []}), encoding="utf-8")

    vault = SkillVault(home=tmp_path)
    assert p.exists()


def test_corrupt_state_recovery_with_backup(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    s = _make_skill("recoverable-skill")
    storage.write_canonical_atomic(s)

    state_file = tmp_path / "brain" / "skill_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("{corrupt state json", encoding="utf-8")

    vault = SkillVault(home=tmp_path)
    new_state = json.loads(state_file.read_text(encoding="utf-8"))
    assert new_state.get("schema_version") == 2
    assert any(e["name"] == "recoverable-skill" for e in new_state["entries"])


def test_update_creates_prior_version_snapshot(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    v1 = _make_skill("versioned-skill", version="1.0.0")
    storage.write_canonical_atomic(v1)

    snap_path = storage.snapshot_prior_version(v1)
    assert snap_path.exists()
    assert "__v1.0.0__" in snap_path.name


def test_failed_update_preserves_original_bytes(tmp_path: Path):
    from hund.learning.commit_controller import CommitController
    controller = CommitController(home=tmp_path)
    storage = SkillStorage(home=tmp_path)

    v1 = _make_skill("safe-update", version="1.0.0")
    storage.write_canonical_atomic(v1)
    orig_bytes = storage.get_canonical_path("safe-update", "global").read_bytes()

    # Attempt update with broken tool
    bad_v2 = Skill(
        schema_version=1,
        name="safe-update",
        domain="general",
        status="draft",
        triggers=("trig",),
        when_to_use="When updated.",
        steps=("Step 1",),
        required_tools=("missing_tool_xyz",),
        forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
        safety_level="confirm",
        verification=("Verify",),
        version="1.1.0",
    )
    ok, msg = controller.commit_skill_draft(bad_v2)
    assert not ok

    curr_bytes = storage.get_canonical_path("safe-update", "global").read_bytes()
    assert curr_bytes == orig_bytes


def test_update_preserves_pin_equip_disposition(tmp_path: Path):
    from hund.learning.commit_controller import CommitController
    controller = CommitController(home=tmp_path)
    storage = SkillStorage(home=tmp_path)
    vault = SkillVault(home=tmp_path)

    v1 = _make_skill("pinned-update", version="1.0.0")
    v1_pinned = replace(v1, user_pinned=True)
    storage.write_canonical_atomic(v1_pinned)
    vault.sync_scoped_state([v1_pinned], desired_equip="pinned-update")
    vault.equip("pinned-update")

    # Update to v1.1.0
    v2 = replace(v1, version="1.1.0")
    ok, receipt = controller.commit_skill_draft(v2, desired_disposition="auto")
    assert ok

    active_skills = vault.get_active_skills()
    assert any(s.name == "pinned-update" for s in active_skills)


def test_atomic_rollback_bytes_and_vault_state(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    v1 = _make_skill("rollback-skill", version="1.0.0")
    storage.write_canonical_atomic(v1)
    storage.snapshot_prior_version(v1)

    v2 = _make_skill("rollback-skill", version="1.1.0")
    storage.write_canonical_atomic(v2)

    ok, msg, restored = storage.rollback_skill("rollback-skill", target_version="1.0.0")
    assert ok
    assert restored is not None
    assert restored.version == "1.0.0"

    canonical = storage.get_canonical_path("rollback-skill", "global")
    data = json.loads(canonical.read_text(encoding="utf-8"))
    assert data["version"] == "1.0.0"


def test_failed_rollback_leaves_canonical_intact(tmp_path: Path):
    storage = SkillStorage(home=tmp_path)
    v1 = _make_skill("stable-skill", version="1.0.0")
    storage.write_canonical_atomic(v1)
    orig_bytes = storage.get_canonical_path("stable-skill", "global").read_bytes()

    ok, msg, restored = storage.rollback_skill("stable-skill", target_version="9.9.9")
    assert not ok
    assert restored is None

    curr_bytes = storage.get_canonical_path("stable-skill", "global").read_bytes()
    assert curr_bytes == orig_bytes


def test_read_does_not_mutate_legacy_file_bytes(tmp_path: Path):
    """Prove that reading legacy skills does NOT perform write-on-read."""
    storage = SkillStorage(home=tmp_path)
    target = storage.get_canonical_path("legacy-read", "global")
    target.parent.mkdir(parents=True, exist_ok=True)

    legacy_raw = {
        "schema_version": 1,
        "name": "legacy-read",
        "domain": "test",
        "status": "active",
        "triggers": ["test"],
        "when_to_use": "When testing.",
        "steps": ["Step 1"],
        "required_tools": [],
        "forbidden_actions": [],
        "safety_level": "read_only",
        "verification": ["Verify"],
    }
    raw_json_bytes = json.dumps(legacy_raw, indent=4).encode("utf-8")
    target.write_bytes(raw_json_bytes)

    # Read via load_domain_skills
    skills = load_domain_skills(home=tmp_path)
    assert len(skills) == 1
    loaded = skills[0]
    assert loaded.name == "legacy-read"
    assert loaded.artifact_version == 1
    assert loaded.lineage_id.startswith("lin_")

    # Verify on-disk file was NOT modified by the read
    assert target.read_bytes() == raw_json_bytes


def test_authorized_write_persists_canonical_lineage_and_version(tmp_path: Path):
    """Prove that an authorized write writes current canonical schema with stable lineage."""
    storage = SkillStorage(home=tmp_path)
    s = _make_skill("canonical-write", version="1.0.0")
    assert s.artifact_version == 1
    assert s.lineage_id.startswith("lin_")

    target = storage.write_canonical_atomic(s)
    saved_data = json.loads(target.read_text(encoding="utf-8"))

    assert saved_data["lineage_id"] == s.lineage_id
    assert saved_data["artifact_version"] == 1
    assert saved_data["publication_status"] == "published"
    assert saved_data["schema_version"] == 1


def test_injected_write_failure_preserves_prior_file(tmp_path: Path, monkeypatch):
    """Prove that a failure during atomic write leaves prior canonical file intact."""
    storage = SkillStorage(home=tmp_path)
    v1 = _make_skill("safe-atomic-fail", version="1.0.0")
    storage.write_canonical_atomic(v1)
    orig_bytes = storage.get_canonical_path("safe-atomic-fail", "global").read_bytes()

    def _exploding_replace(src, dst, max_retries=5):
        raise IOError("Disk full simulation")

    monkeypatch.setattr("hund.skills.storage._fsync_replace", _exploding_replace)

    v2 = replace(v1, version="2.0.0", artifact_version=2)
    with pytest.raises(IOError, match="Disk full"):
        storage.write_canonical_atomic(v2)

    # Original file is preserved without corruption
    curr_bytes = storage.get_canonical_path("safe-atomic-fail", "global").read_bytes()
    assert curr_bytes == orig_bytes
