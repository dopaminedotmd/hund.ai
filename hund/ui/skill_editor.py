"""Pure logic for the in-place skill editor (Gate 3 §2.5.2).

Cursor arithmetic works on a plain text string with a single char offset and
treats every ``\\n`` as one character, so editing JSON buffers is simple and
deterministic. Save/validation reuse the real Skill dataclass + validator.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..skills.model import Skill
from ..skills.validator import validate as validate_skill


def split_lines(text: str) -> list[str]:
    return text.split("\n")


def offset_to_line_col(text: str, offset: int) -> tuple[int, int]:
    lines = split_lines(text)
    pos = max(0, min(offset, len(text)))
    consumed = 0
    for line_index, line in enumerate(lines):
        if pos <= consumed + len(line):
            return line_index, pos - consumed
        consumed += len(line) + 1
    last = len(lines) - 1
    return last, len(lines[last]) if last >= 0 else 0


def line_col_to_offset(text: str, line: int, col: int) -> int:
    lines = split_lines(text)
    line = max(0, min(line, len(lines) - 1)) if lines else 0
    col = max(0, min(col, len(lines[line]) if lines else 0))
    return sum(len(item) + 1 for item in lines[:line]) + col


def move_up(text: str, offset: int) -> int:
    line, col = offset_to_line_col(text, offset)
    if line <= 0:
        return 0
    previous_len = len(split_lines(text)[line - 1])
    return line_col_to_offset(text, line - 1, min(col, previous_len))


def move_down(text: str, offset: int) -> int:
    line, col = offset_to_line_col(text, offset)
    lines = split_lines(text)
    if line >= len(lines) - 1:
        return len(text)
    next_len = len(lines[line + 1])
    return line_col_to_offset(text, line + 1, min(col, next_len))


def line_start(text: str, offset: int) -> int:
    line, _col = offset_to_line_col(text, offset)
    return line_col_to_offset(text, line, 0)


def line_end(text: str, offset: int) -> int:
    line, _col = offset_to_line_col(text, offset)
    lines = split_lines(text)
    return line_col_to_offset(text, line, len(lines[line]))


def word_back_start(text: str, offset: int) -> int:
    """Offset of the previous word boundary (hyphen/path aware, modal-style)."""
    index = max(0, min(offset, len(text)))
    while index > 0 and text[index - 1].isspace():
        index -= 1
    if index == 0:
        return 0
    if text[index - 1].isalnum() or text[index - 1] == "_":
        while index > 0 and (text[index - 1].isalnum() or text[index - 1] == "_"):
            index -= 1
    else:
        while (
            index > 0
            and not text[index - 1].isalnum()
            and not text[index - 1].isspace()
            and text[index - 1] != "_"
        ):
            index -= 1
    return index


def parse_and_validate(text: str, original_name: str) -> tuple[Skill | None, str]:
    """Parse editor text into a validated Skill.

    Returns (None, message) on any validation failure; message is safe to show
    in the status bar and the buffer is left untouched.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"Validation error: invalid JSON at line {exc.lineno}"
    if not isinstance(data, dict):
        return None, "Validation error: skill definition must be a JSON object"
    if str(data.get("name", "")).strip() != original_name:
        return None, (
            f"Validation error: 'name' must stay '{original_name}' "
            "(rename by creating a new skill)"
        )
    try:
        skill = Skill.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"Validation error: {exc}"
    issues = validate_skill(skill)
    if issues:
        return None, "Validation error: " + "; ".join(issues[:2])
    return skill, ""


def save_skill(
    skill: Skill,
    *,
    home: Path | None = None,
    workspace: Path | str | None = None,
) -> tuple[bool, str]:
    """Atomically persist an edited skill back to the canonical skill store."""
    from ..skills.scope import compute_workspace_key
    from ..skills.storage import SkillStorage

    workspace_key = (
        compute_workspace_key(workspace) if skill.scope == "project" else "global"
    )
    storage = SkillStorage(home=home)
    path = storage.get_canonical_path(
        skill.name, skill.scope, workspace_key=workspace_key
    )
    if not path.exists():
        return False, f"Cannot save: skill file for '{skill.name}' not found on disk."
    try:
        storage.write_canonical_atomic(skill, workspace_key=workspace_key)
    except OSError as exc:
        return False, f"Could not save skill: {exc}"
    return True, "Skill saved successfully"


def demo() -> None:
    """Self-check for cursor arithmetic and round-trip validation."""
    text = "{\n  \"name\": \"demo\"\n}"
    assert offset_to_line_col(text, 0) == (0, 0)
    assert offset_to_line_col(text, 8) == (1, 6)
    assert line_col_to_offset(text, 1, 0) == 2
    assert line_end(text, 2) == 18
    assert move_up(text, 10) == line_col_to_offset(text, 0, 6)
    assert move_down(text, 2) == line_col_to_offset(text, 2, 0)
    assert word_back_start("abc def", 7) == 4
    skill, msg = parse_and_validate(
        json.dumps(
            {
                "name": "demo",
                "when_to_use": "w",
                "steps": ["s"],
                "triggers": ["demo"],
                "safety_level": "read_only",
                "verification": ["v"],
            }
        ),
        "demo",
    )
    assert skill is not None and not msg, msg
    bad, msg = parse_and_validate("{broken", "demo")
    assert bad is None and "invalid JSON" in msg
    renamed, msg = parse_and_validate(
        json.dumps({"name": "other", "when_to_use": "w"}), "demo"
    )
    assert renamed is None and "must stay" in msg
    print("skill_editor self-check ok")


if __name__ == "__main__":
    demo()
