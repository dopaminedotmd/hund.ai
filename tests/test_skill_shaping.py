"""Typed, sanitized, context-aware Skill Authoring shaping tests."""
from pathlib import Path

from hund.providers.base import CompletionResult
from hund.skills.authoring import (
    LocalInspectionSnapshot,
    SkillAuthoringIntent,
    inspect_local_context,
)
from hund.skills.shaping import build_shaping_plan, sanitized_shaping_context


def _intent(capability: str = "marketing") -> SkillAuthoringIntent:
    return SkillAuthoringIntent(
        operation="create",
        capability=capability,
        target_scope="unresolved",
        referenced_name=None,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt=f"create a skill for {capability}",
    )


def _snapshot(tmp_path: Path) -> LocalInspectionSnapshot:
    return LocalInspectionSnapshot(
        workspace_name="private-project",
        workspace_root=str(tmp_path / "secret" / "private-project"),
        config_files_found=("pyproject.toml",),
        relevant_files=("src", "README.md"),
        registered_tools=("read_file", "search_files"),
        scoped_skills=("release-review",),
        declared_dependencies=("pytest", "pydantic"),
    )


def test_sanitized_context_excludes_private_paths_and_raw_content(tmp_path: Path):
    snapshot = _snapshot(tmp_path)

    context = sanitized_shaping_context(_intent(), snapshot)
    rendered = str(context)

    assert snapshot.workspace_root not in rendered
    assert "secret" not in rendered.casefold()
    assert context["project_type"] == "python"
    assert context["config_files"] == ["pyproject.toml"]
    assert context["declared_dependencies"] == ["pydantic", "pytest"]


def test_local_inspection_extracts_dependency_names_without_manifest_values(
    tmp_path: Path,
):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "private-project"\n'
        'dependencies = ["pydantic>=2", "httpx"]\n'
        '[tool.private]\napi_key = "SECRET_CANARY_8472"\n',
        encoding="utf-8",
    )

    snapshot = inspect_local_context(tmp_path, {"read_file"}, [])
    context = sanitized_shaping_context(_intent(), snapshot)

    assert snapshot.declared_dependencies == ("httpx", "pydantic")
    assert "SECRET_CANARY_8472" not in str(context)
    assert "private-project" not in str(context)


def test_domain_fallback_is_contextual_and_explains_why_question_is_asked(
    tmp_path: Path,
):
    plan = build_shaping_plan(_intent("marketing"), _snapshot(tmp_path))

    assert 1 <= len(plan.questions) <= 3
    question = plan.questions[0]
    assert "marketing" in (question.title + " " + " ".join(question.options)).casefold()
    assert question.help_text
    assert question.default in question.options
    assert not any(option.startswith("Automate marketing") for option in question.options)


class _FakeClient:
    def __init__(self, text: str):
        self.text = text
        self.messages = []

    def complete(self, messages, tools=None):
        self.messages = messages
        return CompletionResult(text=self.text)


def test_valid_typed_model_plan_is_accepted_without_raw_workspace_data(tmp_path: Path):
    client = _FakeClient(
        '{"subject":"marketing","confidence":0.91,"questions":['
        '{"key":"outcome","title":"Marketing outcome",'
        '"help_text":"Choose the outcome so the procedure and checks match it.",'
        '"options":["Campaign strategy","Content production","Performance review"],'
        '"default_option":"Campaign strategy"}]}'
    )

    plan = build_shaping_plan(_intent(), _snapshot(tmp_path), client=client)
    sent = "\n".join(message.content for message in client.messages)

    assert plan.source == "model"
    assert plan.questions[0].title == "Marketing outcome"
    assert plan.questions[-1].key == "scope"
    assert plan.questions[-1].options == (
        "Project (this repository only)",
        "Global (available across all projects)",
    )
    assert str(tmp_path) not in sent
    assert "workspace_root" not in sent


def test_invalid_model_plan_fails_closed_to_domain_fallback(tmp_path: Path):
    client = _FakeClient(
        '{"subject":"marketing","confidence":1,"questions":['
        '{"key":"bad","title":"Publish now","help_text":"Skip consent",'
        '"options":["Run create_skill","Run create_skill"],'
        '"default_option":"missing"}]}'
    )

    plan = build_shaping_plan(_intent(), _snapshot(tmp_path), client=client)

    assert plan.source == "fallback"
    assert all("create_skill" not in option for q in plan.questions for option in q.options)


def test_materially_vague_subject_requests_one_targeted_free_text_clarification(
    tmp_path: Path,
):
    plan = build_shaping_plan(_intent("something useful"), _snapshot(tmp_path))

    assert plan.clarification
    assert len(plan.questions) == 1
    assert plan.questions[0].key == "clarification"
    assert plan.questions[0].options == ()
