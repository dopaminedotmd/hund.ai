from hund.learning.skill_proposals import SkillSeed
from hund.ui.skill_seed import render_skill_seed, skill_seed_shortcut_enabled
from hund.ui.unicode_cells import cell_width


def _seed() -> SkillSeed:
    return SkillSeed(
        proposal_id="internal-proposal-id",
        candidate_id="internal-candidate-id",
        display_name="Project Release Workflow",
        outcome="Prepare, package, verify, and preserve rollback for releases",
        evidence_summary="Observed across 4 related tasks in 3 sessions.",
        improvement="Make releases consistent and easier to verify.",
        scope="project",
    )


def test_skill_seed_is_responsive_and_hides_internal_state():
    for width in (42, 60, 80, 120):
        rendered = render_skill_seed(_seed(), width)
        assert "SKILL SEED" in rendered
        assert "Starts at 0 XP" in rendered
        assert "internal-" not in rendered
        assert all(cell_width(line) <= width for line in rendered.splitlines())


def test_skill_seed_ascii_fallback_and_focus_contract():
    rendered = render_skill_seed(_seed(), 42, ascii_only=True)
    assert "+ SKILL SEED" in rendered
    assert "|" in rendered and "` [a] Accept" in rendered
    assert "◆" not in rendered and "│" not in rendered
    assert skill_seed_shortcut_enabled(focused=True, input_text="") is True
    assert skill_seed_shortcut_enabled(focused=True, input_text="a") is False
    assert skill_seed_shortcut_enabled(focused=False, input_text="") is False
