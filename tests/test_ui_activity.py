from __future__ import annotations

from hund.ui.activity import ActivityStatus, ActivityTimeline, activity_group, describe_tool


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
    timeline.finish(event_id, ActivityStatus.COMPLETE, duration_s=0.4)
    assert timeline.render_lines() == ["  ┊ ✓ searched the web for Hund · 0.4s"]


def test_activity_timeline_groups_related_web_events() -> None:
    timeline = ActivityTimeline()
    first = timeline.start("web_open", "read source one")
    timeline.finish(first, ActivityStatus.COMPLETE, duration_s=0.2)
    second = timeline.start("web_open", "read source two")
    timeline.finish(second, ActivityStatus.COMPLETE, duration_s=0.3)
    assert timeline.render_lines()[0] == "  ┊ ✓ read 2 relevant pages · 0.5s"


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

