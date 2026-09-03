"""agyD/9 — live-QA fixes: start-page spec progress, human-text editor,
visible save feedback, click-select + click-cursor, [a]/[p] skill keys.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hund.ui.render import build_startup_banner
from hund.ui.screen_render import (
    catalog_click_selection,
    render_skill_editor,
    render_specialisation_management,
    skill_detail_lines,
)
from hund.ui.skill_editor import (
    click_to_offset,
    parse_and_validate,
    save_skill,
)
from hund.ui.snapshots import (
    CatalogSpecialisation,
    SkillItem,
    SkillsSnapshot,
)


# ---- start page specialisations show level + progress bar ----------------
def _rt(active, projections=()):
    stats = {name: {"progress": 0} for name in ("clarity", "precision", "efficiency", "endurance", "mastery")}

    def _compute_all():
        return stats

    def _get_active(self, workspace=None):
        return active

    def _project(skills, **kwargs):
        return projections

    return SimpleNamespace(
        stats=_compute_all,
        active=_get_active,
        project=_project,
        profile=SimpleNamespace(),
        cfg=None,
        workspace=None,
    )


def _projection(capability_id, level, percent):
    return SimpleNamespace(
        capability_id=capability_id,
        display_name=capability_id,
        level=level,
        progress_percent=percent,
    )


def test_start_page_specialisations_show_level_and_progress(monkeypatch):
    active = [
        SimpleNamespace(domain="backend", name="python-fastapi", capability_id="python-fastapi"),
        SimpleNamespace(domain="backend", name="react-tui", capability_id="react-tui"),
        SimpleNamespace(domain="frontend", name="git-workflow", capability_id="git-workflow"),
    ]
    projections = (
        _projection("python-fastapi", 2, 78),
        _projection("react-tui", 1, 50),
        _projection("git-workflow", 1, 58),
    )
    rt = _rt(active, projections)
    monkeypatch.setattr("hund.stats.compute_all", rt.stats)
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_active_skills", rt.active)
    monkeypatch.setattr("hund.skills.vault.SkillVault.get_core_skills", lambda self: [])
    monkeypatch.setattr("hund.ui.render.project_active_skill_xp", rt.project)

    banner = build_startup_banner(rt, width=100)
    backend_line = next(line for line in banner.splitlines() if "● backend" in line)
    # max member level 2, mean of 78/50 = 64.
    assert "L2" in backend_line and "64%" in backend_line
    assert "█" in backend_line and "░" in backend_line
    frontend_line = next(line for line in banner.splitlines() if "● frontend" in line)
    assert "L1" in frontend_line and "58%" in frontend_line


# ---- human-text editor round trip ----------------------------------------
def _item() -> SkillItem:
    return SkillItem(
        name="editor-demo",
        domain="demo",
        xp=0,
        level=1,
        tier="Novice",
        percent=0,
        lifecycle_state="active",
        vault_state="equipped",
        triggers=("editor-demo",),
        tools=("tool-x",),
        safety_level="read_only",
        provenance=(),
        when_to_use="Use in editor tests.",
        scope="global",
        version="1.0.0",
        steps=("Step one.", "Step two."),
        verification=("Verified.",),
    )


def _seed_json(home: Path, name: str = "editor-demo") -> dict:
    data = {
        "schema_version": 1,
        "name": name,
        "domain": "demo",
        "status": "active",
        "lifecycle_state": "active",
        "vault_state": "equipped",
        "triggers": ["editor-demo"],
        "when_to_use": "Use in editor tests.",
        "steps": ["Step one.", "Step two."],
        "required_tools": ["tool-x"],
        "forbidden_actions": [],
        "safety_level": "read_only",
        "verification": ["Verified."],
        "examples": [],
        "version": "1.0.0",
        "scope": "global",
    }
    skills_dir = home / "brain" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def test_editor_uses_human_text_and_merges_onto_real_skill(tmp_path: Path):
    base = _seed_json(tmp_path)
    item = _item()
    # _enter_edit loads exactly the read-view text into the buffer.
    human = "\n".join(skill_detail_lines(item))
    assert '"name"' not in human and "steps:" in human

    edited = human.replace("Step two.", "Step two edited via text.")
    skill, msg = parse_and_validate(edited, "editor-demo", base=base)
    assert skill is not None and not msg, msg
    assert skill.steps == ("Step one.", "Step two edited via text.")

    ok, saved = save_skill(skill, home=tmp_path)
    assert ok and saved == "Skill saved successfully"
    on_disk = json.loads(
        (tmp_path / "brain/skills/editor-demo.json").read_text(encoding="utf-8")
    )
    assert on_disk["steps"][1] == "Step two edited via text."
    # Untouched fields survive the merge (nothing curated away).
    assert on_disk["triggers"] == ["editor-demo"]
    assert on_disk["verification"] == ["Verified."]
    assert on_disk["required_tools"] == ["tool-x"]


def test_editor_text_parser_guards_domain_and_unknown_lines():
    base = {
        "name": "editor-demo", "domain": "demo", "scope": "global",
        "version": "1.0.0", "safety_level": "read_only",
        "triggers": ["editor-demo"], "when_to_use": "w",
        "steps": ["s"], "required_tools": [], "verification": [],
        "forbidden_actions": [], "examples": [],
    }
    text = (
        "\nname: editor-demo\ndomain: demo\n\nwhen_to_use:\n  Use it.\n\n"
        "triggers:\n  - editor-demo\n\nsteps:\n  1. Do it.\n\n"
        "verification:\n  - Checked.\n"
    )
    skill, msg = parse_and_validate(text, "editor-demo", base=base)
    assert skill is not None and not msg, msg

    renamed, msg = parse_and_validate(
        text.replace("name: editor-demo", "name: other"), "editor-demo", base=base
    )
    assert renamed is None and "must stay" in msg

    domain_touched, msg = parse_and_validate(
        text.replace("domain: demo", "domain: other"), "editor-demo", base=base
    )
    assert domain_touched is None and "domain" in msg

    unknown, msg = parse_and_validate(
        text.replace("when_to_use:", "mystery_field:"), "editor-demo", base=base
    )
    assert unknown is None and "unknown skill field" in msg

    missing_base, msg = parse_and_validate(text, "editor-demo", base=None)
    assert missing_base is None and "no on-disk skill file" in msg


def test_editor_status_line_is_visible_inside_editor_frame():
    out = render_skill_editor(
        "editor-demo",
        "\n".join(skill_detail_lines(_item())),
        cursor=0,
        width=80,
        height=16,
        status="Save failed: invalid step",
    )
    assert "Save failed: invalid step" in out
    assert "[Line 1, Col 1 · EDIT · Mouse Scroll]" in out


# ---- click mapping --------------------------------------------------------
def _snapshot() -> SkillsSnapshot:
    skill = SkillItem(
        name="python-fastapi",
        domain="backend",
        xp=0,
        level=2,
        tier="Expert",
        percent=78,
        lifecycle_state="active",
        vault_state="equipped",
        triggers=("fastapi",),
        tools=(),
        safety_level="safe",
        provenance=(),
        when_to_use="Usage text",
        scope="global",
    )
    spec = CatalogSpecialisation("fullstack-builder", 2, 70, ("python-fastapi",))
    return SkillsSnapshot(equipped=(skill,), parked=(), specialisations=(spec,))


def test_catalog_click_selects_the_clicked_row():
    snapshot = _snapshot()
    # skills_lines layout (no wrapping at width 80): blank, SKILLS header,
    # skill row, blank, SPECIALISATIONS header, spec row, blanks/sections...
    assert catalog_click_selection(snapshot, width=80, height=24, scroll=0, y=1) is None
    assert catalog_click_selection(snapshot, width=80, height=24, scroll=0, y=3) == 0
    assert catalog_click_selection(snapshot, width=80, height=24, scroll=0, y=6) == 1
    assert catalog_click_selection(snapshot, width=80, height=24, scroll=0, y=23) is None


def test_editor_click_maps_to_character_offset():
    text = "first line\nsecond line"
    # y=1 is the first content row; cursor at 0 splices "█" before the first
    # char, so clicking the first visible char lands on raw col 0.
    assert click_to_offset(text, 0, width=80, height=20, scroll=0, x=4, y=1) == 0
    # Clicking the second line (y=2) at its start maps to offset 11.
    assert click_to_offset(text, 0, width=80, height=20, scroll=0, x=3, y=2) == 11
    # Clicks on chrome rows do nothing.
    assert click_to_offset(text, 0, width=80, height=20, scroll=0, x=3, y=0) is None


def test_two_pane_footer_advertises_inspect_and_activate_park():
    snapshot = _snapshot()
    out = render_specialisation_management(
        snapshot, spec_cursor=0, member_cursor=0, focus="right", width=80, height=24
    )
    assert "[Enter] Inspect" in out
    assert "[a] Activate" in out and "[p] Park" in out
    assert "Toggle active/parked" not in out
