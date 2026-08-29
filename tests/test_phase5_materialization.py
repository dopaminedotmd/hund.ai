from datetime import datetime, timedelta, timezone
from pathlib import Path

from hund.config import HundConfig
from hund.learning.destination_router import CompletedTurnObservation
from hund.learning.skill_proposals import (
    ProposalState,
    SkillProposalStore,
    materialize_accepted_proposal,
)
from hund.skills.authoring import PublicationReceipt
from hund.skills.loader import load_domain_skills
from hund.skills.storage import SkillStorage
from hund.store.sqlite import connect


NOW = datetime(2026, 8, 26, 12, tzinfo=timezone.utc)


def _observation(
    *,
    session_id: str,
    run_id: str,
    intent: str = "Every time run this recurring release workflow",
    scope: str = "project",
    workspace_id: str = "repo-a",
) -> CompletedTurnObservation:
    return CompletedTurnObservation(
        session_id=session_id,
        turn_id=f"turn-{run_id}",
        run_id=run_id,
        workspace_id=workspace_id,
        user_text=intent,
        assistant_text="1. Read the release inputs\n2. Build the package\n3. Verify rollback",
        tool_names=("read_file",),
        verified=True,
        scope=scope,
    )


def test_phase5c_defaults_to_materialization_enabled():
    cfg = HundConfig()
    assert cfg.enable_skill_observation is True
    assert cfg.enable_skill_proposals is True
    assert cfg.enable_skill_materialization is True


def test_materialize_accepted_proposal_success(tmp_path):
    db = tmp_path / "hund.db"
    home = tmp_path / "home"
    ws = tmp_path / "repo-a"
    ws.mkdir(parents=True, exist_ok=True)
    store = SkillProposalStore(db)

    # 1. Gather evidence across 2 sessions
    assert store.observe(_observation(session_id="s1", run_id="r1"), now=NOW) is None
    seed = store.observe(_observation(session_id="s2", run_id="r2"), now=NOW + timedelta(hours=1))
    assert seed is not None

    # 2. Accept proposal
    accepted = store.respond(seed.proposal_id, "accept", now=NOW + timedelta(hours=2))
    assert accepted is not None
    assert accepted.state == ProposalState.ACCEPTED.value

    # 3. Materialize proposal
    ok, receipt = materialize_accepted_proposal(
        seed.proposal_id,
        db_path=db,
        home=home,
        workspace_path=ws,
        desired_disposition="equip",
    )
    assert ok is True
    assert isinstance(receipt, PublicationReceipt)
    assert receipt.action == "created"
    assert receipt.version == "1.0.0"
    assert receipt.personal_skill_xp == 0
    assert receipt.vault_state == "equipped"

    # 4. Verify canonical storage
    loaded = load_domain_skills(home, workspace=ws)
    assert any(s.name == receipt.skill_name and s.scope == "project" for s in loaded)


def test_materialize_global_proposal_success(tmp_path):
    db = tmp_path / "hund.db"
    home = tmp_path / "home"
    store = SkillProposalStore(db)

    assert store.observe(
        _observation(session_id="s1", run_id="r1", scope="global", workspace_id=""),
        now=NOW,
    ) is None
    seed = store.observe(
        _observation(session_id="s2", run_id="r2", scope="global", workspace_id=""),
        now=NOW + timedelta(hours=1),
    )
    assert seed is not None

    store.respond(seed.proposal_id, "accept", now=NOW)
    ok, receipt = materialize_accepted_proposal(
        seed.proposal_id,
        db_path=db,
        home=home,
        workspace_path=None,
        desired_disposition="vault",
    )
    assert ok is True
    assert isinstance(receipt, PublicationReceipt)
    assert receipt.scope == "global"
    assert receipt.vault_state == "vaulted"

    loaded = load_domain_skills(home)
    assert any(s.name == receipt.skill_name and s.scope == "global" for s in loaded)


def test_materialize_rejects_unaccepted_or_declined_proposal(tmp_path):
    db = tmp_path / "hund.db"
    home = tmp_path / "home"
    store = SkillProposalStore(db)

    store.observe(_observation(session_id="s1", run_id="r1"), now=NOW)
    seed = store.observe(_observation(session_id="s2", run_id="r2"), now=NOW + timedelta(hours=1))
    assert seed is not None

    store.respond(seed.proposal_id, "decline", now=NOW)
    ok, err = materialize_accepted_proposal(seed.proposal_id, db_path=db, home=home)
    assert ok is False
    assert "not in accepted state" in str(err).lower()


def test_materialize_blocks_dangerous_tools(tmp_path):
    db = tmp_path / "hund.db"
    home = tmp_path / "home"
    store = SkillProposalStore(db)

    store.observe(_observation(session_id="s1", run_id="r1"), now=NOW)
    seed = store.observe(_observation(session_id="s2", run_id="r2"), now=NOW + timedelta(hours=1))
    assert seed is not None
    store.respond(seed.proposal_id, "accept", now=NOW)

    # Manually inject forbidden tool into candidate in DB to test gate rejection
    conn = connect(db)
    conn.execute(
        "UPDATE skill_candidates SET tool_names=? WHERE candidate_id=?",
        ('["delete_file", "read_file"]', seed.candidate_id),
    )
    conn.commit()
    conn.close()

    ok, err = materialize_accepted_proposal(seed.proposal_id, db_path=db, home=home)
    assert ok is False
    assert "rejected" in str(err).lower() or "validation" in str(err).lower()


def test_materialize_update_existing_skill_bumps_version_and_snapshots(tmp_path):
    db = tmp_path / "hund.db"
    home = tmp_path / "home"
    ws = tmp_path / "repo-a"
    ws.mkdir(parents=True, exist_ok=True)
    store = SkillProposalStore(db)

    # 1. Create first version
    store.observe(_observation(session_id="s1", run_id="r1"), now=NOW)
    seed1 = store.observe(_observation(session_id="s2", run_id="r2"), now=NOW + timedelta(hours=1))
    assert seed1 is not None
    store.respond(seed1.proposal_id, "accept", now=NOW + timedelta(hours=2))
    ok1, receipt1 = materialize_accepted_proposal(
        seed1.proposal_id, db_path=db, home=home, workspace_path=ws
    )
    assert ok1 is True
    assert receipt1.action == "created"
    assert receipt1.version == "1.0.0"

    # 2. Refined workflow candidate after quiet period
    intent2 = "Every time run this recurring release workflow with changelog"
    store.observe(
        _observation(session_id="s3", run_id="r3", intent=intent2),
        now=NOW + timedelta(days=4),
    )
    seed2 = store.observe(
        _observation(session_id="s4", run_id="r4", intent=intent2),
        now=NOW + timedelta(days=4, hours=1),
    )
    assert seed2 is not None
    store.respond(
        seed2.proposal_id,
        "apply_edit",
        edit_text=f"Call it {receipt1.skill_name}",
        now=NOW + timedelta(days=4, hours=2),
    )
    store.respond(seed2.proposal_id, "accept", now=NOW + timedelta(days=4, hours=3))
    ok2, receipt2 = materialize_accepted_proposal(
        seed2.proposal_id, db_path=db, home=home, workspace_path=ws
    )
    assert ok2 is True
    assert receipt2.action == "updated"
    assert receipt2.version == "1.1.0"
    assert receipt2.personal_skill_xp == 0
