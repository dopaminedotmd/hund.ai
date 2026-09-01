from __future__ import annotations

import pytest

from hund.ui.activity import ActivityStatus, ActivityTimeline, activity_group, describe_tool
from hund.ui.unicode_cells import cell_width


def test_activity_groups_observed_tools_without_reasoning_text() -> None:
    assert activity_group("web_search") == "web_search"
    assert activity_group("web_open") == "web_read"
    assert activity_group("terminal", verification=True) == "verification"
    assert describe_tool("web_search", {"query": "Hund architecture"}) == (
        "searched the web for Hund architecture"
    )
    assert describe_tool("write_file", {"path": "fullscreen.py"}) == "modified fullscreen.py"
    assert describe_tool("terminal", {"command": "pytest -q"}) == "ran targeted tests"


def test_activity_timeline_replaces_running_state() -> None:
    timeline = ActivityTimeline()
    event_id = timeline.start("web_search", "searched the web for Hund")
    assert timeline.render_lines() == ["  ┊ ⟳ searched the web for Hund"]
    timeline.finish(event_id, ActivityStatus.COMPLETE, duration_s=0.9)
    assert timeline.render_lines() == ["  ┊ ✓ searched the web for Hund · 0.9s"]


@pytest.mark.parametrize("width", [42, 60, 80])
def test_activity_lines_fit_the_available_width(width: int) -> None:
    timeline = ActivityTimeline()
    event_id = timeline.start(
        "search_files",
        "searched a deeply nested workspace target with a long query",
    )
    timeline.finish(event_id, ActivityStatus.ERROR, duration_s=12.3, detail="permission denied")

    assert all(cell_width(line) <= width for line in timeline.render_lines(width))


def test_activity_timeline_renders_grouped_read_events() -> None:
    timeline = ActivityTimeline()
    first = timeline.start("web_open", "read source one")
    timeline.finish(first, ActivityStatus.COMPLETE, duration_s=0.2)
    second = timeline.start("web_open", "read source two")
    timeline.finish(second, ActivityStatus.COMPLETE, duration_s=0.3)
    lines = timeline.render_lines()
    assert lines[0] == "  ┊ ✓ read relevant pages          2 sources · 0.5s"
    assert lines[1] == "  ╰─ cross-checked · 0.5s"


def test_activity_capsule_only_for_verified_complex_or_failed_work() -> None:
    simple = ActivityTimeline()
    one = simple.start("read_file", "read README.md")
    simple.finish(one, ActivityStatus.COMPLETE, duration_s=0.1)
    assert len(simple.render_lines()) == 1

    verified = ActivityTimeline()
    check = verified.start("terminal", "ran pytest", group="verification")
    verified.finish(check, ActivityStatus.COMPLETE, duration_s=1.2)
    assert verified.render_lines()[-1] == "  ╰─ clean run · 1.2s"

    holds = ActivityTimeline()
    edit_ev = holds.start("write_file", "modified file.py", group="edit")
    holds.finish(edit_ev, ActivityStatus.COMPLETE, duration_s=0.5)
    test_ev = holds.start("terminal", "ran targeted tests", group="verification")
    holds.finish(test_ev, ActivityStatus.COMPLETE, duration_s=1.5)
    assert holds.render_lines()[-1] == "  ╰─ change holds · 2.0s"

    failed = ActivityTimeline()
    event = failed.start("terminal", "ran build")
    failed.finish(event, ActivityStatus.ERROR, duration_s=0.2, detail="exit code 1")
    assert failed.render_lines()[-1] == "  ╰─ stopped · 0.2s"
