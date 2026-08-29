from datetime import datetime, timedelta, timezone

from hund.learning.destination_router import CompletedTurnObservation
from hund.learning.runtime import RuntimeLearningAdapter
from hund.learning.skill_proposals import (
    ProposalState,
    SkillProposalStore,
    natural_proposal_action,
)
from hund.store.sqlite import connect
from hund.agent import sessions
from hund.config import HundConfig


NOW = datetime(2026, 8, 26, 12, tzinfo=timezone.utc)


def _observation(
    *,
    session_id: str,
    run_id: str,
    intent: str = "Every time run this recurring release workflow",
) -> CompletedTurnObservation:
    return CompletedTurnObservation(
        session_id=session_id,
        turn_id=f"turn-{run_id}",
        run_id=run_id,
        workspace_id="repo-a",
        user_text=intent,
        assistant_text="1. Read the release inputs\n2. Build the package\n3. Verify rollback",
        tool_names=("read_file",),
        verified=True,
        scope="project",
    )


def test_durable_evidence_survives_restart_and_requires_two_sessions(tmp_path):
    db = tmp_path / "hund.db"
    assert SkillProposalStore(db).observe(
        _observation(session_id="s1", run_id="r1"), now=NOW
    ) is None

    seed = SkillProposalStore(db).observe(
        _observation(session_id="s2", run_id="r2"), now=NOW + timedelta(hours=1)
    )
    assert seed is not None
    assert seed.scope == "project"
    assert seed.starts_at_xp == 0
    assert "2 related tasks in 2 sessions" in seed.evidence_summary


def test_session_pacing_and_global_quiet_period_queue_candidates(tmp_path):
    store = SkillProposalStore(tmp_path / "hund.db", quiet_days=3)
    assert store.observe(_observation(session_id="a1", run_id="a1"), now=NOW) is None
    assert store.observe(
        _observation(session_id="a2", run_id="a2"), now=NOW
    ) is not None

    other = "Every time run this recurring campaign workflow"
    assert store.observe(
        _observation(session_id="b1", run_id="b1", intent=other),
        now=NOW + timedelta(hours=1),
    ) is None
    assert store.observe(
        _observation(session_id="b2", run_id="b2", intent=other),
        now=NOW + timedelta(days=1),
    ) is None
    assert any(
        item.state == ProposalState.QUEUED.value
        for item in store.list_candidates()
    )
    assert store.observe(
        _observation(session_id="b3", run_id="b3", intent=other),
        now=NOW + timedelta(days=4),
    ) is not None


def test_only_one_unsolicited_proposal_per_session(tmp_path):
    store = SkillProposalStore(tmp_path / "hund.db", quiet_days=0)
    store.observe(_observation(session_id="s1", run_id="a1"), now=NOW)
    assert store.observe(
        _observation(session_id="s2", run_id="a2"), now=NOW
    ) is not None
    other = "Every time run this recurring campaign workflow"
    store.observe(
        _observation(session_id="s1", run_id="b1", intent=other), now=NOW
    )
    assert store.observe(
        _observation(session_id="s2", run_id="b2", intent=other), now=NOW
    ) is None
    assert any(
        item.state == ProposalState.QUEUED.value
        for item in store.list_candidates()
    )


def test_weak_evidence_decays_before_a_late_repeat(tmp_path):
    store = SkillProposalStore(tmp_path / "hund.db", decay_days=30)
    store.observe(_observation(session_id="s1", run_id="r1"), now=NOW)
    assert store.observe(
        _observation(session_id="s2", run_id="r2"),
        now=NOW + timedelta(days=31),
    ) is None


def test_decline_never_edit_and_unsuppress_are_durable(tmp_path):
    store = SkillProposalStore(tmp_path / "hund.db", quiet_days=0)
    store.observe(_observation(session_id="s1", run_id="r1"), now=NOW)
    seed = store.observe(
        _observation(session_id="s2", run_id="r2"), now=NOW
    )
    assert seed is not None

    editing = store.respond(seed.proposal_id, "edit", now=NOW)
    assert editing is not None and editing.state == ProposalState.EDITING.value
    revised = store.respond(
        seed.proposal_id,
        "apply_edit",
        edit_text="Call it Release Guard. Make it global. Do not web-search.",
        now=NOW,
    )
    assert revised is not None
    assert revised.display_name == "Release Guard"
    assert revised.scope == "global"
    assert revised.research_after_accept is False
    assert revised.changed_summary == "name, scope, research"

    declined = store.respond(seed.proposal_id, "decline", now=NOW)
    assert declined is not None and declined.state == ProposalState.DECLINED.value
    summary = store.list_candidates({ProposalState.DECLINED.value})
    assert len(summary) == 1
    assert store.unsuppress(summary[0].candidate_id) is True
    assert store.list_candidates({ProposalState.DECLINED.value}) == ()


def test_corrupt_candidate_is_quarantined(tmp_path):
    db = tmp_path / "hund.db"
    store = SkillProposalStore(db)
    store.observe(_observation(session_id="s1", run_id="r1"), now=NOW)
    conn = connect(db)
    conn.execute("UPDATE skill_candidates SET steps='not-json'")
    conn.commit()
    conn.close()

    assert store.list_candidates() == ()
    conn = connect(db)
    assert conn.execute(
        "SELECT COUNT(*) FROM skill_candidate_quarantine"
    ).fetchone()[0] == 1
    conn.close()


def test_flags_keep_shadow_constructor_zero_write(tmp_path):
    db = tmp_path / "disabled.db"
    RuntimeLearningAdapter(
        db_path=db,
        skill_observation_enabled=True,
        skill_proposals_enabled=False,
    )
    assert not db.exists()


def test_phase5_rollout_flags_are_independent():
    cfg = HundConfig(enable_skill_materialization=False)
    assert cfg.enable_skill_observation is True
    assert cfg.enable_skill_proposals is True
    assert cfg.enable_skill_materialization is False
    default_cfg = HundConfig()
    assert default_cfg.enable_skill_materialization is True


def test_runtime_uses_durable_store_only_in_proposal_mode(tmp_path, monkeypatch):
    db = tmp_path / "hund.db"
    event = type(
        "Event",
        (),
        {
            "event_type": "verification_completed",
            "payload_redacted": {"passed": True},
            "tool_name": "read_file",
        },
    )()
    monkeypatch.setattr(
        sessions,
        "messages_for_run",
        lambda *_args: [
            ("user", "Every time run this recurring release workflow"),
            ("assistant", "1. Read inputs\n2. Build package\n3. Verify rollback"),
        ],
    )
    monkeypatch.setattr(
        "hund.learning.runtime.list_events_by_run",
        lambda *_args, **_kwargs: [event],
    )

    class Sink:
        def __init__(self):
            self.seeds = []

        def skill_seed(self, seed):
            self.seeds.append(seed)

    sink = Sink()
    RuntimeLearningAdapter(
        db_path=db,
        skill_observation_enabled=True,
        skill_proposals_enabled=True,
    )._observe_skill_need("s1", "t1", "r1", "repo-a", sink)
    RuntimeLearningAdapter(
        db_path=db,
        skill_observation_enabled=True,
        skill_proposals_enabled=True,
    )._observe_skill_need("s2", "t2", "r2", "repo-a", sink)
    assert len(sink.seeds) == 1


def test_natural_actions_are_exact_and_do_not_steal_normal_prompts():
    assert natural_proposal_action("accept") == "accept"
    assert natural_proposal_action("inte nu") == "later"
    assert natural_proposal_action("make it global") == "edit"
    assert natural_proposal_action("analyze this repository") is None
