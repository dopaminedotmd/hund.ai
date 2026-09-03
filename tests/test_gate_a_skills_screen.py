"""Tests for Gate A6: /skills truthful labels, discriminated selection, and inspect Enter binding."""
import pytest

from hund.ui.snapshots import SkillItem, SkillProposalItem, SkillsSnapshot
from hund.ui.screen_render import skills_lines, render_skills, skill_detail_lines
from hund.ui.screen_state import ScreenController, DestinationView


class TestSkillsScreenTruthfulLabels:
    def _create_snapshot(self) -> SkillsSnapshot:
        equipped = (
            SkillItem(
                name="api-release-checklist",
                domain="backend",
                xp=100,
                level=2,
                tier="Apprentice",
                percent=40,
                lifecycle_state="active",
                vault_state="equipped",
                triggers=("api release",),
                tools=("git",),
                safety_level="safe",
                provenance=(),
                when_to_use="When releasing APIs",
                scope="project",
            ),
        )
        parked = (
            SkillItem(
                name="docker-build",
                domain="devops",
                xp=50,
                level=1,
                tier="Novice",
                percent=20,
                lifecycle_state="active",
                vault_state="vaulted",
                triggers=("docker",),
                tools=("shell",),
                safety_level="confirm",
                provenance=(),
                when_to_use="When building docker images",
                scope="global",
            ),
        )
        proposals = (
            SkillProposalItem(
                candidate_id="prop_1",
                name="marketing-outreach",
                scope="project",
                state="deferred",
            ),
        )
        return SkillsSnapshot(equipped=equipped, parked=parked, proposals=proposals)

    def test_screen_title_is_skills_not_specializations(self):
        snap = self._create_snapshot()
        rendered = render_skills(snap, width=80, height=24)
        assert "SKILLS (1)" in rendered
        assert "SPECIALIZATIONS" not in rendered

    def test_section_headers_are_truthful(self):
        snap = self._create_snapshot()
        lines = skills_lines(snap, width=80, selected=0)
        text = "\n".join(lines)
        assert "SKILLS (1)" in text
        assert "VAULT (1)" in text
        assert "PROPOSALS (1)" in text
        assert "SPECIALISATIONS (0)" in text
        assert "EQUIPPED SKILLS" not in text
        assert "SKILL SEEDS" not in text

    def test_skill_detail_render_and_back_contract(self):
        snap = self._create_snapshot()
        detail_rendered = render_skills(snap, width=80, height=24, detail_name="api-release-checklist")
        assert "SKILL DETAIL · api-release-checklist" in detail_rendered
        assert "When releasing APIs" in detail_rendered
        assert "[←] Back" in detail_rendered

    def test_screen_controller_step_back_from_detail_restores_state(self):
        ctrl = ScreenController(destination=DestinationView.SKILLS)
        ctrl.selected["skills"] = 1
        ctrl.scroll["skills"] = 2
        ctrl.detail["skills"] = "api-release-checklist"

        # Step back closes detail, leaves destination, selection, and scroll intact
        result = ctrl.step_back()
        assert result == "detail"
        assert ctrl.detail.get("skills") is None
        assert ctrl.destination == DestinationView.SKILLS
        assert ctrl.selected["skills"] == 1
        assert ctrl.scroll["skills"] == 2
