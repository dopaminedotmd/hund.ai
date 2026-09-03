"""agyD/6 — Gate 3 §2.5.2: in-place skill editor save + validation."""
import json
from pathlib import Path

from hund.ui.screen_render import render_skill_editor
from hund.ui.skill_editor import (
    line_end,
    move_down,
    move_up,
    parse_and_validate,
    save_skill,
    word_back_start,
)
from hund.ui.snapshots import SkillItem
from hund.ui.screen_state import DestinationView, ScreenController


def _valid_text(name: str = "editor-demo") -> str:
    return json.dumps(
        {
            "name": name,
            "domain": "demo",
            "when_to_use": "Use in editor tests.",
            "triggers": ["editor-demo"],
            "steps": ["Step one.", "Step two."],
            "safety_level": "read_only",
            "verification": ["Verified."],
            "version": "1.0.0",
        },
        indent=2,
    )


def _seed_skill(home: Path, name: str = "editor-demo") -> None:
    skills_dir = home / "brain" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / f"{name}.json").write_text(_valid_text(name), encoding="utf-8")


def test_validation_accepts_valid_and_rejects_broken_or_renamed():
    skill, msg = parse_and_validate(_valid_text(), "editor-demo")
    assert skill is not None and not msg
    bad, msg = parse_and_validate('{"name": "editor-demo",', "editor-demo")
    assert bad is None and "invalid JSON" in msg
    renamed, msg = parse_and_validate(_valid_text("other-name"), "editor-demo")
    assert renamed is None and "must stay" in msg
    # Missing required fields are caught by the Skill validator.
    missing, msg = parse_and_validate(
        json.dumps({"name": "editor-demo"}), "editor-demo"
    )
    assert missing is None and "Validation error" in msg


def test_save_persists_edited_steps_to_disk(tmp_path: Path):
    _seed_skill(tmp_path)
    skill, msg = parse_and_validate(
        _valid_text().replace("Step two.", "Step two edited."), "editor-demo"
    )
    assert skill is not None and not msg
    ok, saved_msg = save_skill(skill, home=tmp_path)
    assert ok and "saved" in saved_msg.lower()
    on_disk = json.loads((tmp_path / "brain/skills/editor-demo.json").read_text(encoding="utf-8"))
    assert on_disk["steps"][1] == "Step two edited."


def test_save_requires_existing_canonical_file(tmp_path: Path):
    skill, _ = parse_and_validate(_valid_text(), "editor-demo")
    ok, msg = save_skill(skill, home=tmp_path)
    assert not ok and "not found" in msg


def test_render_skill_editor_title_meta_footer_and_cursor():
    out = render_skill_editor(
        "editor-demo", _valid_text(), cursor=8, width=80, height=14
    )
    assert "SKILL DETAIL · EDITING · editor-demo" in out
    assert "[EDIT]" in out.splitlines()[0]
    assert "[Ctrl+S] Save" in out
    assert "[Esc] Discard" in out
    assert "[Line 2, Col 7" in out  # cursor offset 8 -> line 2, column 7
    lines = out.splitlines()
    assert any("█" in line for line in lines)


def test_editor_cursor_moves_across_lines():
    text = '{\n  "steps": ["a", "b"]\n}'
    # Line 1 starts at offset 2; moving up from its start lands on line 0 col 0,
    # moving down from line 0 returns to the same column on line 1.
    assert move_up(text, 2) == 0
    assert move_down(text, 0) == 2
    assert line_end(text, 0) == 1  # end of the '{' line
    assert word_back_start("hello world", 11) == 6


def test_screen_controller_holds_editor_state():
    state = ScreenController(destination=DestinationView.SKILLS)
    state.edit_mode = True
    state.edit_buffer_text = '{"name":"x"}'
    state.edit_cursor = 5
    assert state.edit_mode and state.edit_cursor == 5
    # step_back in edit mode exits the editor first.
    assert state.step_back() == "edit"
    assert not state.edit_mode
