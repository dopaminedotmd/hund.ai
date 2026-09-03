"""agyD/0 — Gate 3 UI-infra: ScreenState panel_focus/edit_mode transitions."""
from hund.ui.screen_state import DestinationView, ScreenController


def test_step_back_exits_edit_mode_first():
    c = ScreenController()
    c.destination = DestinationView.SKILLS
    c.detail["skills"] = "some-skill"
    c.edit_mode = True
    assert c.step_back() == "edit"
    assert c.edit_mode is False
    # detail still open after leaving edit mode
    assert c.detail["skills"] == "some-skill"


def test_step_back_panel_right_to_left_then_detail():
    c = ScreenController()
    c.destination = DestinationView.SKILLS
    c.detail["skills"] = "some-skill"
    c.panel_focus["skills"] = "right"
    assert c.step_back() == "panel"
    assert c.panel_focus["skills"] == "left"
    assert c.step_back() == "detail"
    assert c.detail.get("skills") is None


def test_step_back_detail_then_destination_unchanged_for_chat():
    c = ScreenController()
    c.destination = DestinationView.STATS
    assert c.step_back() == "destination"
    assert c.destination is DestinationView.CHAT


def test_escape_in_edit_mode_returns_edit():
    c = ScreenController()
    c.destination = DestinationView.SKILLS
    c.edit_mode = True
    assert c.close_escape() == "edit"
    assert c.edit_mode is False
