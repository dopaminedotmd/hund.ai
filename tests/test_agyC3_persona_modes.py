"""agyC/3 — Spår 11: representation modes + repetition guard (mekanism)."""
from hund.persona_modes import list_modes, mode_for_request, select_variant


def test_five_modes_present_and_have_aliases():
    modes = list_modes()
    keys = [m["key"] for m in modes]
    assert keys == ["static", "technical", "minimal", "poetic", "interactive"]
    assert all(m["aliases"] and m["constraint"] for m in modes)


def test_mode_for_request_detects_styles():
    assert mode_for_request("presentera dig poetiskt")["key"] == "poetic"
    assert mode_for_request("beskriv dig tekniskt")["key"] == "technical"
    assert mode_for_request("kortfattad presentation")["key"] == "minimal"
    assert mode_for_request("vem är du?")["key"] == "static"
    assert mode_for_request("")["key"] == "static"


def test_select_variant_avoids_recent_when_variation_requested():
    mode, alt = select_variant("presentera dig på ett annat sätt", recent_keys=["static", "poetic"])
    assert alt is not None
    assert alt != "static" and alt != "poetic"
    assert alt in {m["key"] for m in list_modes()}


def test_select_variant_no_variation_returns_requested_only():
    mode, alt = select_variant("vem är du?")
    assert mode["key"] == "static"
    assert alt is None


def test_openings_are_identity_safe_and_emoji_free():
    import re

    for m in list_modes():
        ex = m["example"].lower()
        assert "hund" in ex
        assert not re.search(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", m["example"])
        assert "**" not in m["example"]
