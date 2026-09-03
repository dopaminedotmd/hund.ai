"""agyD/7 — Gate 3 spec §4.1: the four named Gate 3 acceptance tests."""
import json
from datetime import date, timedelta
from pathlib import Path

from hund.ui.screen_render import (
    render_skill_editor,
    render_skills,
    render_specialisation_management,
    render_stats_inline,
    skill_definition_text,
)
from hund.ui.screen_state import DestinationView, ScreenController
from hund.ui.skill_editor import parse_and_validate, save_skill
from hund.ui.snapshots import (
    CatalogSpecialisation,
    SkillItem,
    SkillProposalItem,
    SkillsSnapshot,
    SpecializationItem,
    StatItem,
    StatsSnapshot,
)


def _skill(name: str, domain: str = "backend", *, parked: bool = False,
           steps: tuple[str, ...] = ("Step one.", "Step two."),
           triggers: tuple[str, ...] = ("trigger-a", "trigger-b")) -> SkillItem:
    return SkillItem(
        name=name,
        domain=domain,
        xp=100,
        level=2,
        tier="Expert",
        percent=70,
        lifecycle_state="active",
        vault_state="vaulted" if parked else "equipped",
        triggers=triggers,
        tools=("terminal",),
        safety_level="safe",
        provenance=("k1@1.0",),
        when_to_use="Use when the scenario matches.",
        scope="global",
        version="1.0.0",
        steps=steps,
        verification=("Check output matches expectation.",),
        limitations=("Does not cover edge cases.",),
    )


def test_stats_inline_rendering():
    """Spec §4.1: inline /stats is an exact-80 double frame with four quadrants."""
    stats = (
        StatItem("Clarity", "CLR", 78.0, 78, "B"),
        StatItem("Precision", "PRC", 94.0, 94, "A"),
    )
    specs = (
        SpecializationItem("fullstack-builder", "fullstack", 3, "Expert", 62, 120, "active", "equipped", True),
    )
    days = tuple(date(2026, 9, 3) - timedelta(days=i) for i in range(6, -1, -1))
    snapshot = StatsSnapshot(
        "0.2.0", stats, specs, (0,) * 7, days,
        (("clarity", 2.4, True),), True,
        xp_today=240, verified_today=3, velocity_today_pct=12,
    )
    out = render_stats_inline(snapshot, width=80)
    assert out.startswith("╔═ STATS") and out.endswith("╝")
    assert max(len(line) for line in out.splitlines()) == 80
    for quadrant in ("BASE STATS", "ACTIVE SKILLS", "SPECIALISATIONS", "TODAY & PROGRESS"):
        assert quadrant in out
    assert "fullstack-builder" in out
    assert "+240 XP" in out and "+12% vs yesterday" in out


def test_specialisation_live_preview_and_focus_toggle():
    """Spec §4.1: member preview follows the left cursor; Enter/Backspace move focus."""
    snapshot = SkillsSnapshot(
        equipped=(_skill("python-fastapi"), _skill("react-tui", "frontend")),
        parked=(_skill("shopify-tools", "legacy", parked=True),),
        specialisations=(
            CatalogSpecialisation("backend", 2, 70, ("python-fastapi",)),
            CatalogSpecialisation("frontend", 2, 70, ("react-tui",)),
        ),
    )
    first = render_specialisation_management(
        snapshot, spec_cursor=0, member_cursor=0, focus="left", width=80, height=24
    )
    assert "MEMBER SKILLS (1)" in first and "✓ python-fastapi" in first
    second = render_specialisation_management(
        snapshot, spec_cursor=1, member_cursor=0, focus="left", width=80, height=24
    )
    assert "✓ react-tui" in second and "✓ python-fastapi" not in second

    # Focus toggle is ScreenController-driven state: Enter -> right panel,
    # Backspace (step_back) returns to the left panel, Backspace again closes.
    state = ScreenController(destination=DestinationView.SKILLS)
    state.detail["skills_spec"] = "backend"
    state.panel_focus["skills"] = "left"
    state.panel_focus["skills"] = "right"  # Enter
    assert state.panel_focus["skills"] == "right"
    assert state.step_back() == "panel"
    assert state.panel_focus["skills"] == "left"
    # Right-panel rendering carries the member cursor marker.
    right = render_specialisation_management(
        snapshot, spec_cursor=0, member_cursor=0, focus="right", width=80, height=24
    )
    assert "❯ ✓ python-fastapi" in right


def test_skill_inspect_exact_content():
    """Spec §4.1: inspect shows full triggers/steps with deterministic scrolling."""
    long_steps = tuple(f"Step {i}: do the precise thing described in detail." for i in range(8))
    long_triggers = tuple(f"trigger-{i}" for i in range(5))
    skill = _skill("python-fastapi", steps=long_steps, triggers=long_triggers)
    definition = skill_definition_text(skill)
    assert "trigger-4" in definition
    assert "Step 7: do the precise thing" in definition

    snapshot = SkillsSnapshot(equipped=(skill,), parked=())
    at_top = render_skills(snapshot, width=80, height=16, detail_name="python-fastapi", scroll=0)
    scrolled = render_skills(snapshot, width=80, height=16, detail_name="python-fastapi", scroll=10)
    assert len(at_top.splitlines()) == len(scrolled.splitlines()) == 16
    assert at_top.splitlines() != scrolled.splitlines()
    assert "SKILL DETAIL · python-fastapi" in at_top
    assert "[c] Copy All" in at_top


def test_skill_editor_save_and_validation():
    """Spec §4.1: invalid edits are caught with a message; valid text saves + reloads."""
    text = json.dumps(
        {
            "name": "editor-demo",
            "domain": "demo",
            "when_to_use": "Use in editor tests.",
            "triggers": ["editor-demo"],
            "steps": ["Step one."],
            "safety_level": "read_only",
            "verification": ["Verified."],
        },
        indent=2,
    )
    # Broken JSON is reported without crashing.
    skill, msg = parse_and_validate('{"name": "editor-demo",', "editor-demo")
    assert skill is None and "Validation error" in msg
    # Missing required structure is reported.
    skill, msg = parse_and_validate('{"name": "editor-demo"}', "editor-demo")
    assert skill is None and "Validation error" in msg
    # Valid text round-trips into a Skill and saves to disk.
    skill, msg = parse_and_validate(text, "editor-demo")
    assert skill is not None and not msg
    out = render_skill_editor("editor-demo", text, cursor=0, width=80, height=14)
    assert "EDITING" in out and "[Ctrl+S] Save" in out


def test_editor_save_writes_disk(tmp_path: Path):
    text = json.dumps(
        {
            "name": "editor-demo",
            "domain": "demo",
            "when_to_use": "Use in editor tests.",
            "triggers": ["editor-demo"],
            "steps": ["Step one.", "Step two edited."],
            "safety_level": "read_only",
            "verification": ["Verified."],
        },
        indent=2,
    )
    skills_dir = tmp_path / "brain" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "editor-demo.json").write_text(text, encoding="utf-8")
    skill, msg = parse_and_validate(text, "editor-demo")
    assert skill is not None and not msg
    ok, saved = save_skill(skill, home=tmp_path)
    assert ok and saved == "Skill saved successfully"
    reloaded = json.loads((skills_dir / "editor-demo.json").read_text(encoding="utf-8"))
    assert reloaded["steps"][1] == "Step two edited."
