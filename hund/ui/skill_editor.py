"""Pure logic for the in-place skill editor (Gate 3 §2.5.2).

Cursor arithmetic works on a plain text string with a single char offset and
treats every ``\\n`` as one character. The editor edits the SAME human-readable
text as the read view (name:, when_to_use:, steps:, ...), never raw JSON —
agyD/9 QA: William rejected JSON editing. Saving merges the parsed text edits
onto the real on-disk skill so untouched fields survive. JSON buffers are still
accepted for legacy/backward compatibility.
"""
from __future__ import annotations

import json
import re
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


# Labels the human text can carry. Editable scalars map to to_dict keys;
# read-only labels (capability/lifecycle/xp) are recognised and ignored.
_SCALAR_KEYS = {
    "name": "name",
    "domain": "domain",
    "scope": "scope",
    "version": "version",
    "safety": "safety_level",
    "safety_level": "safety_level",
}
_IGNORED_SCALARS = {"capability", "lifecycle", "xp", "safety_level_info"}
_SECTION_LISTS = {"triggers", "tools", "steps", "verification", "limitations", "provenance"}
_PLACEHOLDERS = {"(none declared)", "(no procedure steps declared)", "—"}


def parse_editor_text(text: str, original_name: str) -> tuple[dict[str, Any], str]:
    """Parse the human skill text into an editable to_dict-shaped mapping.

    Returns ({}, message) on malformed text; the message is safe to show in the
    status bar. Fields the text format cannot express are left untouched by the
    caller's merge with the real on-disk skill.
    """
    changes: dict[str, Any] = {}
    active_section: str | None = None  # 'para' | list label | 'steps'
    section_key: str | None = None
    para_lines: list[str] = []
    items: list[str] = []

    def end_section() -> None:
        """Commit the section currently being collected (blank/header/EOF)."""
        nonlocal active_section, section_key, para_lines, items
        if active_section == "para":
            changes["when_to_use"] = " ".join(part.strip() for part in para_lines).strip()
        elif active_section == "steps":
            changes["steps"] = items
        elif active_section == "tools":
            changes["required_tools"] = items
        elif active_section == "limitations":
            changes["limitations"] = items
        elif active_section == "provenance":
            pass  # provenance is not editable from the text view
        elif active_section:  # triggers/verification list
            changes[active_section] = items
        active_section = None
        section_key = None
        para_lines = []
        items = []

    def scalar(label: str, value: str) -> str | None:
        key = _SCALAR_KEYS.get(label)
        if key == "name":
            edited_name = value.strip()
            if edited_name != original_name:
                return (
                    f"Validation error: 'name' must stay '{original_name}' "
                    "(rename by creating a new skill)"
                )
            return None
        if key:
            changes[key] = value.strip()
        return None

    for index, raw in enumerate(text.split("\n"), 1):
        line = raw.rstrip()
        if not line.strip():
            end_section()
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0:
            end_section()
            header = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", stripped)
            if not header:
                return {}, (
                    f"Validation error: line {index}: '{stripped[:40]}' is not a "
                    "valid skill section (expected name:, when_to_use:, steps:, ...)"
                )
            label, rest = header.group(1), header.group(2)
            if label == "when_to_use":
                active_section, section_key = "para", "when_to_use"
                if rest.strip() and rest.strip() not in _PLACEHOLDERS:
                    para_lines.append(rest)
            elif label in _SECTION_LISTS:
                active_section, section_key = label, label
                if rest.strip() and rest.strip() not in _PLACEHOLDERS:
                    items.append(rest)
            elif label in _SCALAR_KEYS or label in _IGNORED_SCALARS:
                err = scalar(label, rest)
                if err:
                    return {}, err
            else:
                return {}, (
                    f"Validation error: line {index}: unknown skill field "
                    f"'{label}'"
                )
        else:
            content = stripped
            if active_section == "para":
                if content not in _PLACEHOLDERS:
                    para_lines.append(content)
            elif active_section == "steps":
                step = re.match(r"^(\d+)\.\s+(.*)$", content)
                if step:
                    if step.group(2) not in _PLACEHOLDERS:
                        items.append(step.group(2))
                else:
                    return {}, (
                        f"Validation error: line {index}: steps must be numbered "
                        f"like '1. {content[:24]}'"
                    )
            elif active_section in ("triggers", "tools", "verification", "limitations", "provenance"):
                if content in _PLACEHOLDERS:
                    continue  # read-view empty-state labels carry no content
                bullet = re.match(r"^-\s+(.*)$", content)
                if bullet:
                    items.append(bullet.group(1))
                else:
                    return {}, (
                        f"Validation error: line {index}: {section_key} entries "
                        f"must start with '- '"
                    )
            else:
                return {}, (
                    f"Validation error: line {index}: unexpected indented text "
                    "outside a section"
                )
    end_section()
    return changes, ""


def parse_and_validate(
    text: str, original_name: str, base: dict[str, Any] | None = None
) -> tuple[Skill | None, str]:
    """Parse editor text into a validated Skill.

    JSON text keeps the legacy whole-document path (base ignored). Human text
    is merged onto ``base`` (the real on-disk to_dict) so fields the text view
    does not show survive the round trip.

    Returns (None, message) on any validation failure; message is safe to show
    in the status bar and the buffer is left untouched.
    """
    if text.lstrip().startswith("{"):
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

    changes, message = parse_editor_text(text, original_name)
    if message:
        return None, message
    if base is None:
        return None, (
            "Validation error: no on-disk skill file for this skill "
            "(cannot resolve edits)."
        )
    if changes.get("name", original_name) != original_name:
        return None, (
            f"Validation error: 'name' must stay '{original_name}' "
            "(rename by creating a new skill)"
        )
    if changes.get("domain") not in (None, base.get("domain", "")):
        return None, (
            "Validation error: 'domain' cannot be changed here — domain XP "
            "aggregation is keyed on it."
        )
    merged = dict(base)
    merged.update(changes)
    merged["name"] = original_name
    merged.pop("limitations", None)
    research = merged.get("research_metadata")
    if not isinstance(research, dict):
        research = {}
    if "limitations" in changes:
        research = dict(research)
        research["limitations"] = changes["limitations"]
    merged["research_metadata"] = research
    try:
        skill = Skill.from_dict(merged)
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


def click_to_offset(
    text: str,
    cursor: int,
    *,
    width: int,
    height: int,
    scroll: int,
    x: int,
    y: int,
) -> int | None:
    """Map a mouse click on the editor viewport to a text offset.

    Mirrors render_skill_editor's geometry (horizontal crop around the cursor,
    never wrapped). ``y`` is the row within the destination window, ``x`` the
    column; (0, 0) is the frame's top-left border.
    """
    content_rows = max(height - 3, 1)
    inner = max(max(20, width - 1) - 6, 16)
    capacity = max(content_rows - 1, 1)
    if y < 1:
        return None
    content_index = y - 1
    if content_index >= min(capacity, content_rows):
        return None  # status line / footer chrome
    raw_lines = split_lines(text)
    line, col = offset_to_line_col(text, cursor)
    effective = max(0, min(scroll, max(0, len(raw_lines) - capacity)))
    if line < effective:
        effective = line
    elif line >= effective + capacity:
        effective = max(0, line - capacity + 1)
    cursor_col = min(col, len(raw_lines[line]) if raw_lines else 0)
    h_scroll = max(0, cursor_col - inner + 6)
    if h_scroll:
        h_scroll = min(h_scroll, (len(raw_lines[line]) if raw_lines else 0) - 1)

    row_index = effective + content_index
    if row_index >= len(raw_lines):
        return None
    raw = raw_lines[row_index]
    # The cursor line is rendered with a spliced block marker.
    display = raw if row_index != line else raw[:cursor_col] + "█" + raw[cursor_col:]
    shown = display[h_scroll:]
    prefix = "…" if h_scroll else ""
    if len(shown) + len(prefix) > inner:
        shown = shown[: inner - len(prefix) - 1] + "…"

    vcol = x - 3  # frame padding: border + two spaces
    if vcol < 0:
        vcol = 0
    if prefix:
        if vcol == 0:
            vcol = 1  # the "…" marks hidden start; land on first shown char
        else:
            vcol -= 1
    if vcol >= len(shown):
        vcol = max(len(shown) - 1, 0)
    # Guard against the trailing truncation marker.
    visible_len = len(shown)
    if visible_len and shown[-1] == "…":
        vcol = min(vcol, visible_len - 2)
    if vcol < 0:
        vcol = 0
    if not display:
        return line_col_to_offset(text, row_index, 0)
    si = min(h_scroll + vcol, len(display) - 1)
    if row_index != line:
        char_col = si
    elif si < cursor_col:
        char_col = si
    elif si == cursor_col:
        char_col = cursor_col
    else:
        char_col = si - 1
    char_col = min(char_col, len(raw))
    return line_col_to_offset(text, row_index, char_col)


def demo() -> None:
    """Self-check for cursor arithmetic, human parse round trip, and clicks."""
    text = "{\n  \"name\": \"demo\"\n}"
    assert offset_to_line_col(text, 0) == (0, 0)
    assert offset_to_line_col(text, 8) == (1, 6)
    assert line_col_to_offset(text, 1, 0) == 2
    assert line_end(text, 2) == 18
    assert move_up(text, 10) == line_col_to_offset(text, 0, 6)
    assert move_down(text, 2) == line_col_to_offset(text, 2, 0)
    assert word_back_start("abc def", 7) == 4

    base = {
        "schema_version": 1,
        "name": "demo",
        "domain": "demo",
        "status": "active",
        "lifecycle_state": "active",
        "vault_state": "equipped",
        "triggers": ["demo"],
        "when_to_use": "w",
        "steps": ["s"],
        "required_tools": [],
        "safety_level": "read_only",
        "verification": ["v"],
        "forbidden_actions": [],
        "examples": [],
    }
    human = (
        "\nname: demo\ndomain: demo\nscope: global\nversion: 1.0.0\n"
        "safety: read_only\ncapability: cap-demo\nxp: 0 XP\n\n"
        "when_to_use:\n  Use for demos only.\n\n"
        "triggers:\n  - demo\n\n"
        "steps:\n  1. First.\n  2. Second.\n\n"
        "verification:\n  - Verified.\n"
    )
    skill, msg = parse_and_validate(human, "demo", base=base)
    assert skill is not None and not msg, msg
    assert skill.steps == ("First.", "Second.") and skill.when_to_use == "Use for demos only."

    renamed, msg = parse_and_validate(
        human.replace("name: demo", "name: other"), "demo", base=base
    )
    assert renamed is None and "must stay" in msg
    domain_touched, msg = parse_and_validate(
        human.replace("domain: demo", "domain: other"), "demo", base=base
    )
    assert domain_touched is None and "domain" in msg
    bad, msg = parse_and_validate("{broken", "demo")
    assert bad is None and "invalid JSON" in msg

    click_text = "\n".join(["hello world", "second line", "third"])
    # Window rows: y=0 border, y=1 first content row, ...
    # Cursor at 0 splices "█" before 'h', so clicking the first visible char
    # after it lands on raw col 0; rows below the cursor line map 1:1.
    assert click_to_offset(click_text, 0, width=80, height=20, scroll=0, x=4, y=1) == 0
    assert click_to_offset(click_text, 0, width=80, height=20, scroll=0, x=3, y=2) == 12
    assert click_to_offset(click_text, 0, width=80, height=20, scroll=0, x=3, y=3) == 24
    assert click_to_offset(click_text, 12, width=80, height=20, scroll=0, x=4, y=2) == 12
    assert click_to_offset(click_text, 0, width=80, height=20, scroll=0, x=3, y=0) is None
    assert click_to_offset(click_text, 0, width=80, height=20, scroll=0, x=3, y=9) is None
    print("skill_editor self-check ok")


if __name__ == "__main__":
    demo()
