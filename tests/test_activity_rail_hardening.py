"""Tests for ActivityTimeline: grouping, fast-turn collapse, and canonical redaction."""
import pytest
from hund.ui.activity import (
    ActivityStatus,
    ActivityTimeline,
    describe_tool,
)


def test_running_event_replaced_on_finish():
    timeline = ActivityTimeline()
    eid = timeline.start("read_file", "read config.json")
    lines_running = timeline.render_lines()
    assert any("⟳" in l and "read config.json" in l for l in lines_running)

    timeline.finish(eid, ActivityStatus.COMPLETE, duration_s=0.85)
    lines_finished = timeline.render_lines()
    assert not any("⟳" in l for l in lines_finished)
    assert any("✓" in l and "0.8s" in l or "0.9s" in l for l in lines_finished)


def test_presentation_only_consecutive_grouping():
    timeline = ActivityTimeline()
    # 3 consecutive reads
    e1 = timeline.start("read_file", "read a.py", group="inspection")
    timeline.finish(e1, ActivityStatus.COMPLETE, duration_s=0.2)
    e2 = timeline.start("read_file", "read b.py", group="inspection")
    timeline.finish(e2, ActivityStatus.COMPLETE, duration_s=0.2)
    e3 = timeline.start("read_file", "read c.py", group="inspection")
    timeline.finish(e3, ActivityStatus.COMPLETE, duration_s=0.2)

    # Underlying events remain 3 distinct events!
    assert len(timeline.events) == 3

    rendered = timeline.render_lines()
    assert any("read relevant files" in l and "3 files" in l for l in rendered)


def test_edits_and_verifications_never_grouped():
    timeline = ActivityTimeline()
    e1 = timeline.start("edit_file", "modified main.py", group="edit")
    timeline.finish(e1, ActivityStatus.COMPLETE, duration_s=0.4)
    e2 = timeline.start("edit_file", "modified utils.py", group="edit")
    timeline.finish(e2, ActivityStatus.COMPLETE, duration_s=0.4)

    rendered = timeline.render_lines()
    # Edits must stay separate!
    assert any("modified main.py" in l for l in rendered)
    assert any("modified utils.py" in l for l in rendered)


def test_fast_turn_collapse_constraints():
    # 1. Fast read-only (< 700ms) with explicit False security -> collapses
    timeline = ActivityTimeline()
    e1 = timeline.start("read_file", "checked the file", group="inspection", security_relevant=False)
    timeline.finish(e1, ActivityStatus.COMPLETE, duration_s=0.3)
    rendered = timeline.render_lines()
    assert len(rendered) == 1
    assert "hund checked the file." in rendered[0]
    assert "0.3s" in rendered[0]

    # 2. Fast write-action (< 700ms) -> does NOT collapse (must show rail)
    timeline_write = ActivityTimeline()
    ew = timeline_write.start("write_file", "modified file.py", group="edit")
    timeline_write.finish(ew, ActivityStatus.COMPLETE, duration_s=0.3)
    rendered_write = timeline_write.render_lines()
    assert any("┊" in l for l in rendered_write)

    # 3. Slow read-action (> 700ms) -> does NOT collapse
    timeline_slow = ActivityTimeline()
    es = timeline_slow.start("read_file", "inspected large database", group="inspection")
    timeline_slow.finish(es, ActivityStatus.COMPLETE, duration_s=1.2)
    rendered_slow = timeline_slow.render_lines()
    assert any("┊" in l for l in rendered_slow)


def test_canonical_redaction_in_tool_descriptions():
    # API key in args/description
    secret_key = "sk-1234567890abcdef1234567890abcdef"
    desc = describe_tool("web_search", {"query": f"key={secret_key}"})
    assert secret_key not in desc
    assert "[REDACTED:secret]" in desc or "REDACTED" in desc

    # Windows user path in args
    win_path = r"C:\Users\William\hund.ai\private_config.json"
    desc_path = describe_tool("read_file", {"path": win_path})
    assert "William" not in desc_path


def test_terminal_heredoc_multiline_sanitized_to_single_line():
    cmd = "python - <<'PY'\nimport sys\nprint('hello')\nPY"
    desc = describe_tool("terminal", {"command": cmd})
    assert "\n" not in desc
    assert desc.startswith("ran python - <<'PY'")
    assert "…" in desc
    assert "import sys" not in desc

