"""agyD/4 — Gate 3 §2.4: specialisation two-pane window (live preview + focus)."""
from hund.ui.screen_render import (
    render_spec_member_remove_modal,
    render_specialisation_management,
)
from hund.ui.screen_state import DestinationView, ScreenController
from hund.ui.snapshots import CatalogSpecialisation, SkillItem, SkillsSnapshot


def _skill(name: str, level: int, percent: int, state: str) -> SkillItem:
    return SkillItem(
        name=name,
        domain="x",
        xp=0,
        level=level,
        tier="Expert",
        percent=percent,
        lifecycle_state="active",
        vault_state=state,
        triggers=(),
        tools=(),
        safety_level="safe",
        provenance=(),
        when_to_use="w",
        scope="global",
    )


def _snapshot() -> SkillsSnapshot:
    return SkillsSnapshot(
        equipped=(
            _skill("python-fastapi", 2, 78, "equipped"),
            _skill("react-tui", 2, 62, "equipped"),
        ),
        parked=(_skill("shopify-liquid", 1, 58, "vaulted"),),
        specialisations=(
            CatalogSpecialisation(
                "backend", 2, 70, ("python-fastapi", "react-tui")
            ),
        ),
        vaulted_specialisations=(
            CatalogSpecialisation(
                "legacy-tools", 0, 0, ("shopify-liquid",)
            ),
        ),
    )


def test_two_pane_live_preview_shows_selected_spec_members():
    snap = _snapshot()
    out = render_specialisation_management(
        snap, spec_cursor=0, member_cursor=0, focus="left", width=80, height=24
    )
    assert "SPECIALISATIONS (1)" in out
    assert "MEMBER SKILLS (2)" in out
    assert "✓ python-fastapi" in out
    assert "✓ react-tui" in out
    assert "backend" in out
    # Right pane live-preview follows the left cursor: vaulted spec members.
    out_vaulted = render_specialisation_management(
        snap, spec_cursor=1, member_cursor=0, focus="left", width=80, height=24
    )
    assert "MEMBER SKILLS (1)" in out_vaulted
    assert "✓ shopify-liquid" in out_vaulted
    assert "✓ python-fastapi" not in out_vaulted


def test_vaulted_spec_listed_once_and_parked_tag():
    out = render_specialisation_management(
        _snapshot(), spec_cursor=0, member_cursor=0, focus="left",
        width=80, height=24,
    )
    # legacy-tools appears only in the VAULT section, tagged [parked].
    assert out.count("legacy-tools") == 1
    assert "[parked]" in out
    assert "VAULT (1)" in out


def test_focus_moves_marker_and_title():
    snap = _snapshot()
    left = render_specialisation_management(
        snap, spec_cursor=0, member_cursor=0, focus="left", width=80, height=24
    )
    right = render_specialisation_management(
        snap, spec_cursor=0, member_cursor=1, focus="right", width=80, height=24
    )
    assert left.splitlines()[0].startswith("╔ SPECIALISATION ")
    assert "SPECIALISATION · backend" in right
    assert "❯ ● backend" in left
    assert "❯ ✓ react-tui" in right  # member cursor landed on member 1


def test_parked_member_is_visible_with_tag():
    snap = SkillsSnapshot(
        equipped=(_skill("react-tui", 2, 62, "equipped"),),
        parked=(_skill("shopify-liquid", 1, 58, "vaulted"),),
        specialisations=(
            CatalogSpecialisation(
                "ecommerce", 1, 55, ("shopify-liquid", "react-tui")
            ),
        ),
    )
    out = render_specialisation_management(
        snap, spec_cursor=0, member_cursor=0, focus="right", width=80, height=24
    )
    assert "MEMBER SKILLS (2)" in out
    assert "react-tui" in out and "shopify-liquid" in out
    assert "react-tui" in out.split("shopify-liquid")[0]  # equipped listed first


def test_remove_member_confirm_modal():
    out = render_spec_member_remove_modal("python-fastapi", "backend", width=80)
    assert "REMOVE MEMBER" in out
    assert "Park python-fastapi?" in out
    assert "[y] Yes · [n] No" in out
    ascii_out = render_spec_member_remove_modal("python-fastapi", "backend", width=80, ascii_only=True)
    assert "╭" not in ascii_out


def test_screen_controller_spec_window_back_priority():
    state = ScreenController(destination=DestinationView.SKILLS)
    state.detail["skills_spec"] = "backend"
    state.panel_focus["skills"] = "right"
    assert state.step_back() == "panel"
    assert state.panel_focus["skills"] == "left"
    assert state.step_back() == "detail"
    assert state.detail.get("skills_spec") is None
    assert state.destination == DestinationView.SKILLS
    assert state.close_escape() == "destination"


def test_empty_snapshot_spec_window_geometry():
    snap = SkillsSnapshot((), ())
    out = render_specialisation_management(
        snap, spec_cursor=0, member_cursor=0, focus="left",
        width=80, height=24,
    )
    assert "(No specialisations yet.)" in out
    assert len(out.splitlines()) == 24
    assert max(len(line) for line in out.splitlines()) <= 79
