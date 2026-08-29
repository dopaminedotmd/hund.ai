"""Tests for ActivityTimeline grouping, confirmation tracking, and fast-turn collapse."""
import pytest
from hund.ui.activity import ActivityStatus, ActivityTimeline, activity_group


def test_activity_group_mapping():
    assert activity_group("read_file") == "read"
    assert activity_group("search_files") == "search"
    assert activity_group("web_search") == "web_search"
    assert activity_group("web_open") == "web_read"
    assert activity_group("write_file") == "edit"
    assert activity_group("terminal") == "execution"
    assert activity_group("terminal", verification=True) == "verification"


def test_consecutive_grouping_same_category():
    timeline = ActivityTimeline()

    # 3 consecutive read_file events
    e1 = timeline.start("read_file", "read file1.py")
    timeline.finish(e1, ActivityStatus.COMPLETE, duration_s=0.1)

    e2 = timeline.start("read_file", "read file2.py")
    timeline.finish(e2, ActivityStatus.COMPLETE, duration_s=0.2)

    e3 = timeline.start("read_file", "read file3.py")
    timeline.finish(e3, ActivityStatus.COMPLETE, duration_s=0.3)

    lines = timeline.render_lines()
    assert any("read relevant files    3 files" in ln for ln in lines)


def test_interleaved_groups_never_merged():
    timeline = ActivityTimeline()

    # read, search, read
    e1 = timeline.start("read_file", "read file1.py")
    timeline.finish(e1, ActivityStatus.COMPLETE, duration_s=0.1)

    e2 = timeline.start("search_files", "searched *.py")
    timeline.finish(e2, ActivityStatus.COMPLETE, duration_s=0.2)

    e3 = timeline.start("read_file", "read file2.py")
    timeline.finish(e3, ActivityStatus.COMPLETE, duration_s=0.1)

    lines = timeline.render_lines()
    # They should NOT be collapsed into "read relevant files 2 files" because search intervened
    assert not any("read relevant files" in ln for ln in lines)


def test_fast_turn_collapse_constraints():
    # Case 1: Fast read-only complete without confirmation and explicit False security -> collapses
    t1 = ActivityTimeline()
    eid = t1.start("read_file", "read config.py", security_relevant=False)
    t1.finish(eid, ActivityStatus.COMPLETE, duration_s=0.3)
    lines1 = t1.render_lines()
    assert len(lines1) == 1
    assert lines1[0].startswith("  hund read config.py.")

    # Case 1b: Default unknown security (None) -> does NOT collapse
    t1b = ActivityTimeline()
    eid1b = t1b.start("read_file", "read config.py")
    t1b.finish(eid1b, ActivityStatus.COMPLETE, duration_s=0.3)
    lines1b = t1b.render_lines()
    assert any("┊ ✓" in ln for ln in lines1b)

    # Case 2: Slow read-only (>0.7s) -> does NOT collapse
    t2 = ActivityTimeline()
    eid2 = t2.start("read_file", "read big_file.py")
    t2.finish(eid2, ActivityStatus.COMPLETE, duration_s=1.2)
    lines2 = t2.render_lines()
    assert any("┊ ✓" in ln for ln in lines2)

    # Case 3: Required confirmation -> does NOT collapse
    t3 = ActivityTimeline()
    eid3 = t3.start("read_file", "read secret.py", required_confirmation=True)
    t3.finish(eid3, ActivityStatus.COMPLETE, duration_s=0.2)
    lines3 = t3.render_lines()
    assert any("┊ ✓" in ln for ln in lines3)

    # Case 4: Security relevant -> does NOT collapse
    t4 = ActivityTimeline()
    eid4 = t4.start("read_file", "read auth.py", security_relevant=True)
    t4.finish(eid4, ActivityStatus.COMPLETE, duration_s=0.2)
    lines4 = t4.render_lines()
    assert any("┊ ✓" in ln for ln in lines4)

    # Case 5: Edit/terminal -> does NOT collapse
    t5 = ActivityTimeline()
    eid5 = t5.start("write_file", "modified foo.py")
    t5.finish(eid5, ActivityStatus.COMPLETE, duration_s=0.2)
    lines5 = t5.render_lines()
    assert any("┊ ✓" in ln for ln in lines5)


def test_mark_confirmation_method():
    timeline = ActivityTimeline()
    eid = timeline.start("terminal", "ran pytest")
    assert not timeline.events[0].required_confirmation

    timeline.mark_confirmation(eid)
    assert timeline.events[0].required_confirmation
