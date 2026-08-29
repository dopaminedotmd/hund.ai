"""Focused contract and migration test suite for Phase 2 Canonical Capability Core."""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from hund.skills.contracts import (
    PUBLICATION_STATUS_PUBLISHED,
    PUBLICATION_STATUS_QUARANTINED,
    VALID_PUBLICATION_STATUSES,
    VALID_RESEARCH_CHOICES,
    PublicationReceipt,
    ResearchChoice,
    ResearchMetadata,
    ResearchSource,
    compute_legacy_lineage_id,
    generate_lineage_id,
    validate_research_source,
)
from hund.skills.model import CURRENT_SCHEMA_VERSION, Skill, from_dict


def _make_sample_skill(**kwargs) -> Skill:
    base = {
        "schema_version": 1,
        "name": "git-workflow",
        "domain": "git",
        "status": "active",
        "triggers": ("git", "commit"),
        "when_to_use": "When managing git operations.",
        "steps": ("Check status", "Stage changes", "Commit with message"),
        "required_tools": ("terminal",),
        "forbidden_actions": ("git push --force",),
        "safety_level": "confirm",
        "verification": ("git status",),
        "capability_id": "git-workflow",
        "scope": "global",
    }
    base.update(kwargs)
    return Skill(**base)


# ============================================================================
# Task 1: Typed Canonical Value Objects & Validation
# ============================================================================


def test_lineage_id_generation_and_determinism():
    # Legacy lineage is deterministic given capability, scope, and workspace_key
    l1 = compute_legacy_lineage_id("marketing-strategy", "global", "global")
    l2 = compute_legacy_lineage_id("marketing-strategy", "global", "global")
    assert l1 == l2
    assert l1.startswith("lin_")
    assert len(l1) >= 16

    # Different scope or capability yields distinct lineage
    l3 = compute_legacy_lineage_id("marketing-strategy", "project", "workspace_abc123")
    assert l1 != l3

    # Fresh lineage generation produces unique IDs
    f1 = generate_lineage_id()
    f2 = generate_lineage_id()
    assert f1 != f2
    assert f1.startswith("lin_")


def test_research_source_sanitization():
    # Valid source
    src = ResearchSource(title="Official Docs", url_or_ref="https://docs.python.org/3/")
    assert src.title == "Official Docs"
    assert src.url_or_ref == "https://docs.python.org/3/"

    # Source containing secret must be rejected
    with pytest.raises(ValueError, match="credential"):
        validate_research_source(
            ResearchSource(title="Leak", url_or_ref="https://api.com?key=sk-123456789012345678901234567890")
        )

    # Source containing private local path must be rejected
    with pytest.raises(ValueError, match="private path"):
        validate_research_source(
            ResearchSource(title="Local Secret", url_or_ref="/Users/william/private_notes.txt")
        )
    with pytest.raises(ValueError, match="private path"):
        validate_research_source(
            ResearchSource(title="Local Secret Win", url_or_ref=r"C:\Users\William\private.txt")
        )


def test_research_metadata_validation():
    # Valid default
    meta = ResearchMetadata()
    assert meta.choice == "not_needed"
    assert meta.sources == ()
    assert meta.freshness_as_of is None

    # Valid with ISO timestamp
    meta2 = ResearchMetadata(
        choice="explicitly_requested",
        sources=(ResearchSource(title="MDN", url_or_ref="https://developer.mozilla.org"),),
        freshness_as_of="2026-08-28T12:00:00Z",
        limitations=("Covers standard Web APIs only",),
    )
    assert meta2.choice in VALID_RESEARCH_CHOICES
    assert len(meta2.sources) == 1

    # Invalid choice
    with pytest.raises(ValueError, match="Invalid research choice"):
        ResearchMetadata(choice="invalid_choice_value")

    # Invalid naive / non-ISO timestamp
    with pytest.raises(ValueError, match="timestamp"):
        ResearchMetadata(freshness_as_of="yesterday afternoon")


def test_skill_canonical_fields_and_validation():
    skill = _make_sample_skill(
        lineage_id="lin_test_12345",
        artifact_version=2,
        publication_status="published",
        publication_receipt_id="rec_pub_001",
    )
    assert skill.lineage_id == "lin_test_12345"
    assert skill.artifact_version == 2
    assert skill.publication_status == "published"
    assert skill.publication_receipt_id == "rec_pub_001"

    # Non-positive artifact_version must fail
    with pytest.raises(ValueError, match="artifact_version"):
        _make_sample_skill(artifact_version=0)
    with pytest.raises(ValueError, match="artifact_version"):
        _make_sample_skill(artifact_version=-1)

    # Invalid publication_status must fail
    with pytest.raises(ValueError, match="publication_status"):
        _make_sample_skill(publication_status="invalid_status")


# ============================================================================
# Task 2: Backward-Compatible Legacy Deserialization
# ============================================================================


def test_legacy_schema_version_1_in_memory_migration():
    legacy_dict = {
        "schema_version": 1,
        "name": "legacy-seo",
        "domain": "marketing",
        "status": "active",
        "triggers": ["seo", "keywords"],
        "when_to_use": "When optimizing page metadata.",
        "steps": ["Analyze headings", "Check meta tags"],
        "required_tools": ["read_file"],
        "forbidden_actions": [],
        "safety_level": "read_only",
        "verification": ["Check html"],
        "capability_id": "legacy-seo",
        "scope": "global",
        # Missing lineage_id, artifact_version, publication_status, research_metadata
    }

    skill = from_dict(legacy_dict)
    assert isinstance(skill, Skill)
    assert skill.name == "legacy-seo"
    assert skill.capability_id == "legacy-seo"
    # Legacy defaults:
    assert skill.artifact_version == 1
    assert skill.publication_status == "published"
    assert skill.lineage_id.startswith("lin_")
    assert skill.research_metadata.choice == "not_needed"

    # Determinism: same dict loaded twice yields exact same lineage_id
    skill2 = from_dict(legacy_dict)
    assert skill.lineage_id == skill2.lineage_id


def test_unknown_future_schema_version_fails_closed():
    future_dict = {
        "schema_version": 999,
        "name": "future-ai-skill",
        "domain": "quantum",
        "status": "active",
        "triggers": ["quantum"],
        "when_to_use": "Future usage",
        "steps": ["Step 1"],
        "required_tools": [],
        "forbidden_actions": [],
        "safety_level": "read_only",
        "verification": ["verify"],
        "capability_id": "future-ai-skill",
    }

    with pytest.raises(ValueError, match="schema"):
        from_dict(future_dict)


# ============================================================================
# Task 4: Artifact Version and Lineage Transitions Matrix
# ============================================================================


def test_version_transition_semantic_vs_non_semantic():
    from hund.skills.contracts import apply_transition

    orig = _make_sample_skill(
        lineage_id="lin_orig_100",
        artifact_version=1,
        vault_state="vaulted",
    )

    # 1. Non-semantic: Equip / Park / Use / Evidence
    s_equipped = apply_transition(orig, transition_type="equip")
    assert s_equipped.lineage_id == orig.lineage_id
    assert s_equipped.artifact_version == 1
    assert s_equipped.vault_state == "equipped"

    s_parked = apply_transition(s_equipped, transition_type="park")
    assert s_parked.lineage_id == orig.lineage_id
    assert s_parked.artifact_version == 1
    assert s_parked.vault_state == "vaulted"

    s_used = apply_transition(orig, transition_type="use_evidence", xp_gain=10)
    assert s_used.lineage_id == orig.lineage_id
    assert s_used.artifact_version == 1
    assert s_used.use_count == orig.use_count + 1

    # 2. Semantic procedure refinement -> version increments exactly once
    s_refined = apply_transition(
        orig,
        transition_type="semantic_update",
        new_steps=("New Step 1", "New Step 2"),
    )
    assert s_refined.lineage_id == orig.lineage_id
    assert s_refined.artifact_version == 2
    assert s_refined.steps == ("New Step 1", "New Step 2")

    # 3. Explicit Fork / Variant -> new lineage with parent references
    s_forked = apply_transition(
        orig,
        transition_type="fork",
        new_name="git-workflow-variant",
    )
    assert s_forked.lineage_id != orig.lineage_id
    assert s_forked.parent_lineage_ref == orig.lineage_id
    assert s_forked.parent_version_ref == orig.artifact_version
    assert s_forked.artifact_version == 1


# ============================================================================
# Task 5: Publication Receipt Consistency
# ============================================================================


def test_publication_receipt_consistency_with_skill():
    from hund.skills.contracts import create_publication_receipt, validate_receipt_against_skill

    skill = _make_sample_skill(
        lineage_id="lin_verified_99",
        artifact_version=3,
        publication_status="published",
        publication_receipt_id="rec_pub_99",
    )

    receipt = create_publication_receipt(
        skill=skill,
        action="updated",
        receipt_id="rec_pub_99",
        checks_passed=12,
        total_checks=12,
    )

    assert receipt.publication_receipt_id == "rec_pub_99"
    assert receipt.lineage_id == "lin_verified_99"
    assert receipt.artifact_version == 3
    assert receipt.scope == "global"
    assert receipt.publication_status == "published"

    # Validation must pass for matching artifact/receipt
    assert validate_receipt_against_skill(receipt, skill) is True

    # Mismatched version must fail validation
    mismatched_skill = _make_sample_skill(
        lineage_id="lin_verified_99",
        artifact_version=4,
        publication_receipt_id="rec_pub_99",
    )
    assert validate_receipt_against_skill(receipt, mismatched_skill) is False


# ============================================================================
# Task 10: Non-Destructive Migration Golden Path (Isolated Fixtures)
# ============================================================================


def test_phase2_golden_path_migration_and_rollback(tmp_path):
    """Execute complete 7-step isolated migration golden path per Phase 2 spec."""
    import json
    from hund.skills.storage import SkillStorage
    from hund.skills.loader import load_domain_skills
    from hund.skills.vault import SkillVault

    storage = SkillStorage(home=tmp_path)
    vault = SkillVault(home=tmp_path)

    # 1. Setup representative legacy global and project skills
    global_path = storage.get_canonical_path("legacy-global", "global")
    global_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_global_raw = {
        "schema_version": 1,
        "name": "legacy-global",
        "domain": "marketing",
        "status": "active",
        "triggers": ["marketing"],
        "when_to_use": "When planning campaigns.",
        "steps": ["Step A", "Step B"],
        "required_tools": [],
        "forbidden_actions": [],
        "safety_level": "read_only",
        "verification": ["Verify"],
    }
    raw_bytes = json.dumps(legacy_global_raw, indent=2).encode("utf-8")
    global_path.write_bytes(raw_bytes)

    # 2. Prove no file changes on read
    skills = load_domain_skills(home=tmp_path)
    assert len(skills) == 1
    migrated_in_memory = skills[0]
    assert migrated_in_memory.name == "legacy-global"
    assert migrated_in_memory.artifact_version == 1
    assert migrated_in_memory.lineage_id.startswith("lin_")
    assert global_path.read_bytes() == raw_bytes  # Bit-for-bit identical on disk

    # 3. Perform an authorized write and inspect current serialized schema
    saved_target = storage.write_canonical_atomic(migrated_in_memory)
    saved_json = json.loads(saved_target.read_text(encoding="utf-8"))
    assert saved_json["lineage_id"] == migrated_in_memory.lineage_id
    assert saved_json["artifact_version"] == 1
    assert saved_json["publication_status"] == "published"
    assert saved_json["schema_version"] == 1

    # 4. Reload and prove stable lineage/version/scope identity
    reloaded_skills = load_domain_skills(home=tmp_path)
    reloaded = reloaded_skills[0]
    assert reloaded.lineage_id == migrated_in_memory.lineage_id
    assert reloaded.artifact_version == 1
    assert reloaded.scope == "global"

    # 5. Snapshot prior version, write v1.1.0, then test atomic rollback
    storage.snapshot_prior_version(reloaded)
    v2_skill = _make_sample_skill(
        name="legacy-global",
        lineage_id=reloaded.lineage_id,
        artifact_version=2,
        version="1.1.0",
    )
    storage.write_canonical_atomic(v2_skill)
    assert json.loads(saved_target.read_text(encoding="utf-8"))["artifact_version"] == 2

    ok, msg, restored = storage.rollback_skill("legacy-global", target_version="1.0.0")
    assert ok is True
    assert restored is not None
    assert restored.version == "1.0.0"
    assert restored.lineage_id == reloaded.lineage_id

    # 6. Load an unknown future schema and prove fail-closed behavior
    future_path = storage.get_canonical_path("future-skill", "global")
    future_path.write_text(json.dumps({"schema_version": 999, "name": "future-skill"}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        from_dict(json.loads(future_path.read_text(encoding="utf-8")))

    # 7. Verify vault/equip/evidence operations do not duplicate or increment version
    vault.sync_scoped_state([restored], desired_equip="legacy-global")
    active = vault.get_active_skills()
    assert any(s.name == "legacy-global" for s in active)
    assert active[0].artifact_version == 1
    assert active[0].lineage_id == reloaded.lineage_id
