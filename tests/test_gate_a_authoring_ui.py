"""Tests for Gate A5: Complete authoring component, layout, and contrast tokens."""
import pytest
from dataclasses import dataclass

from hund.skills.authoring import AuthoringState
from hund.skills.contracts import PublicationReceipt
from hund.ui.skill_authoring import render_authoring_stepper, render_publication_receipt
from hund.ui.theme import make_pt_style, get_skin


@dataclass
class DummyOption:
    key: str
    label: str


@dataclass
class DummyStepperView:
    phase: str
    title: str
    subject: str = ""
    skill_name: str = ""
    description: str = ""
    scope: str = ""
    limitations: tuple[str, ...] = ()
    step_index: int = 1
    step_total: int = 2
    question_key: str = ""
    options: tuple[DummyOption, ...] = ()


class TestAuthoringStepperLayout:
    def test_ready_structured_in_separate_rows(self):
        view = DummyStepperView(
            phase=AuthoringState.READY,
            title="Skill Ready",
            skill_name="api-release-checklist",
            description="Automates release validation for endpoints.",
            scope="project",
            limitations=("Requires git access",),
            options=(
                DummyOption("publish", "Publish & use"),
                DummyOption("vault", "Save to vault"),
                DummyOption("decline", "Decline"),
            ),
        )
        for w in (120, 80, 60, 42):
            rendered = render_authoring_stepper(view, selected_index=0, width=w)
            assert "SKILL READY" in rendered
            assert "api-release-checklist" in rendered
            assert "SCOPE" in rendered
            assert "Publish & use" in rendered
            # Check diamond / rail structure
            assert "◆" in rendered or "#" in rendered
            assert "│" in rendered or "|" in rendered
            assert "└" in rendered or "`" in rendered

    def test_ready_receipt_rendering_at_all_widths(self):
        receipt = PublicationReceipt(
            action="created",
            skill_name="api-release-checklist",
            scope="project",
            artifact_version="1.0.0",
            lifecycle_state="active",
            vault_state="equipped",
            personal_skill_xp=50,
        )
        for w in (120, 80, 60, 42):
            rendered = render_publication_receipt(receipt, width=w)
            assert "api-release-checklist" in rendered
            assert "SKILL CREATED" in rendered
            assert "/skills" in rendered

    def test_theme_contains_growth_cream_and_pt_styles(self):
        skin = get_skin("marshmallow")
        tokens = skin["tokens"]
        assert "growth_gold" in tokens
        assert "growth_ochre" in tokens
        assert "growth_brass" in tokens
        pt_style = make_pt_style()
        assert pt_style is not None
