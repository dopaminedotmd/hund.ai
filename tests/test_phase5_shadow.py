from hund.agent import sessions
from hund.learning.destination_router import (
    CompletedTurnObservation,
    LearningDestination,
    route_learning_destination,
)
from hund.learning.skill_need import ShadowSkillNeedEngine, candidate_identity
from hund.learning.runtime import RuntimeLearningAdapter


def _observation(**changes):
    values = dict(
        session_id="s1", turn_id="t1", run_id="r1", workspace_id="repo-a",
        user_text="Every time run this recurring workflow",
        assistant_text="1. Read the input\n2. Transform it\n3. Verify the output",
        tool_names=("read_file",), completed=True, verified=True, scope="project",
    )
    values.update(changes)
    return CompletedTurnObservation(**values)


def test_router_is_conservative_and_provider_neutral():
    decision = route_learning_destination(_observation())
    assert decision.destination is LearningDestination.SKILL_CANDIDATE
    assert route_learning_destination(_observation(completed=False)).destination is LearningDestination.NONE
    assert route_learning_destination(_observation(user_text="Create a skill for this")).destination is LearningDestination.NONE


def test_project_identity_includes_workspace_but_global_omits_it():
    assert candidate_identity(_observation(workspace_id="a")) != candidate_identity(_observation(workspace_id="b"))
    assert candidate_identity(_observation(scope="global", workspace_id="a")) == candidate_identity(_observation(scope="global", workspace_id="b"))


def test_shadow_requires_two_unique_runs_and_emits_once():
    engine = ShadowSkillNeedEngine()
    assert engine.observe(_observation()) is None
    candidate = engine.observe(_observation(run_id="r2", turn_id="t2"))
    assert candidate is not None
    assert candidate.evidence_run_ids == ("r1", "r2")
    assert engine.observe(_observation(run_id="r3", turn_id="t3")) is None


def test_shadow_gates_verification_coverage_risk_and_procedure():
    assert ShadowSkillNeedEngine().observe(_observation(verified=False)) is None
    assert ShadowSkillNeedEngine(coverage_gap=lambda _: False).observe(_observation()) is None
    assert ShadowSkillNeedEngine().observe(_observation(tool_names=("delete_file",))) is None
    assert ShadowSkillNeedEngine().observe(_observation(assistant_text="Done.")) is None


def test_shadow_memory_is_bounded():
    engine = ShadowSkillNeedEngine(max_candidates=2)
    for index in range(3):
        engine.observe(_observation(
            run_id=f"r{index}", workspace_id=f"repo-{index}",
            user_text=f"Every time run recurring workflow {index}",
        ))
    assert len(engine._evidence) == 2


def test_run_query_is_exact_and_ordered(tmp_path):
    sid = sessions.create(home=tmp_path)
    sessions.add_message(sid, "user", "one", home=tmp_path, run_id="r1")
    sessions.add_message(sid, "assistant", "two", home=tmp_path, run_id="r1")
    sessions.add_message(sid, "user", "other", home=tmp_path, run_id="r2")
    assert sessions.messages_for_run(sid, "r1", home=tmp_path) == [("user", "one"), ("assistant", "two")]


def test_runtime_shadow_redacts_and_only_publishes_behind_second_flag(monkeypatch):
    seen = []

    class Engine:
        def observe(self, observation):
            seen.append(observation)
            return object()

    class Sink:
        def __init__(self):
            self.seeds = []

        def skill_seed(self, seed):
            self.seeds.append(seed)

    event = type("Event", (), {
        "event_type": "verification_completed", "payload_redacted": {"passed": True},
        "tool_name": "read_file",
    })()
    monkeypatch.setattr(sessions, "messages_for_run", lambda *_: [
        ("user", "Every time use sk-secretsecretsecretsecret in this workflow"),
        ("assistant", "1. Read input\n2. Verify output"),
    ])
    monkeypatch.setattr("hund.learning.runtime.list_events_by_run", lambda *_args, **_kwargs: [event])
    sink = Sink()
    adapter = RuntimeLearningAdapter(
        skill_observation_enabled=True,
        skill_proposals_enabled=False,
        skill_need_engine=Engine(),
    )
    adapter._observe_skill_need("s", "t", "r", "repo", sink)
    assert "secretsecretsecret" not in seen[0].user_text
    assert sink.seeds == []

    adapter.skill_proposals_enabled = True
    adapter._observe_skill_need("s", "t", "r", "repo", sink)
    assert len(sink.seeds) == 1


def test_runtime_observation_flag_short_circuits_before_session_read(monkeypatch):
    monkeypatch.setattr(sessions, "messages_for_run", lambda *_: (_ for _ in ()).throw(AssertionError))
    RuntimeLearningAdapter(
        skill_observation_enabled=False, skill_proposals_enabled=True
    )._observe_skill_need("s", "t", "r", "repo", object())
