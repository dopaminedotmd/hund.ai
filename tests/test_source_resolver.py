from hund.learning.source_resolver import SourceResolver


def test_source_resolver_observe_before_assume_plan():
    decision = SourceResolver().plan(
        "Läs pyproject.toml och kontrollera den", ["pyproject.toml"]
    )
    assert decision.source_type == "workspace"
    assert decision.observations[0].tool_name == "read_file"
    assert decision.observations[0].args == {"path": "pyproject.toml"}


def test_source_resolver_prioritizes_workspace_version_state():
    decision = SourceResolver().plan("Är paketet installerat?")
    assert decision.source_type == "workspace"
    assert decision.observations


def test_volatile_claim_uses_official_web():
    decision = SourceResolver().plan("What is the latest supported version?")
    assert decision.source_type == "official_web"


def test_internal_rationale_is_not_part_of_observation_args():
    decision = SourceResolver().plan("Kontrollera config.json", ["config.json"])
    assert "rationale" not in decision.observations[0].args
