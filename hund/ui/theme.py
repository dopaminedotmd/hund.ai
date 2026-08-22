"""Design tokens and visual styling for hund.ui.

Unified token architecture: Truecolor (hex) with 16-ANSI fallback for standard
terminals. Standardized single-line box-drawing (┌─┐, │, └─┘), block progress bars,
and strict zero-emoji invariants.
"""
from __future__ import annotations

import re

# -- Core Design Tokens (Hex + 16-ANSI fallback) ---------------------------
COLOR_TOKENS: dict[str, dict[str, str]] = {
    "text":   {"hex": "#E3E3E4", "rich": "white",          "pt": "ansiwhite"},
    "dim":    {"hex": "#6E7380", "rich": "bright_black",   "pt": "ansibrightblack"},
    "cyan":   {"hex": "#4EBCD5", "rich": "cyan",           "pt": "ansicyan"},
    "green":  {"hex": "#50FA7B", "rich": "green",          "pt": "ansigreen"},
    "yellow": {"hex": "#F1FA8C", "rich": "bright_yellow",   "pt": "ansibrightyellow"},
    "red":    {"hex": "#FF5555", "rich": "red",            "pt": "ansired"},
}

HUND_TEXT = "#E3E3E4"    # Primary bone white text
HUND_DIM = "#6E7380"     # Muted structural borders & metadata
HUND_CYAN = "#4EBCD5"    # Accent / Hund identity
HUND_GREEN = "#50FA7B"   # User prompt & positive confirmation
HUND_YELLOW = "#F1FA8C"  # Master prestige / warnings
HUND_RED = "#FF5555"     # Danger / blocked actions

HUND_FG = HUND_TEXT

EMDASH = "—"  # Tier placeholder when unranked

# Rich style names (16-ANSI safe) for Rich console rendering
TIER_RICH: dict[str, str] = {
    "Novice": "dim",
    "Apprentice": "green",
    "Adept": "cyan",
    "Expert": "white",
    "Master": "bright_yellow",
    EMDASH: "dim",
}

# Prompt Toolkit style names for bottom_toolbar
TIER_PT: dict[str, str] = {
    "Novice": "ansibrightblack",
    "Apprentice": "ansigreen",
    "Adept": "ansicyan",
    "Expert": "ansiwhite",
    "Master": "ansibrightyellow",
    EMDASH: "ansibrightblack",
}

# Chat flow separation tokens (no emojis)
USER_PREFIX = "user >"
USER_PREFIX_RICH = "bold green"
HUND_INDENT = "  "
HUND_RAIL = "│ "
SYSTEM_BULLET = "•"
SEPARATOR_CHAR = "─"

HUND_ASCII_COMPACT = (
    "  ┬ ┬ ┬ ┬ ┌┐┌ ┌┬┐\n"
    "  ├─┤ │ │ │││  ││\n"
    "  ┴ ┴ └─┘ ┘└┘ ─┴┘"
)


STAT_ABBR: dict[str, str] = {
    "clarity": "CLR",
    "precision": "PRC",
    "efficiency": "EFF",
    "endurance": "END",
    "mastery": "MAS",
}
STAT_ORDER: list[str] = ["clarity", "precision", "efficiency", "endurance", "mastery"]

BAR_FILL = "█"   # Full block
BAR_EMPTY = "░"  # Light shade
BAR_WIDTH = 8


def tier_rich(tier: str | None) -> str:
    return TIER_RICH.get(tier or "", "dim")


def tier_pt(tier: str | None) -> str:
    return TIER_PT.get(tier or "", "ansibrightblack")


# -- Boxify Helper (Single-line geometric box-drawing) -----------------------

def boxify(
    title: str = "",
    content: list[str] | str | None = None,
    *,
    width: int = 70,
    border_style: str = "dim",
    title_style: str = "bold cyan",
) -> str:
    """Wrap content in clean geometric single-line box borders (no emojis).

    Example:
    ┌── TITLE ────────────────────────────────────────────────────────┐
    │ content line 1                                                  │
    └─────────────────────────────────────────────────────────────────┘
    """
    inner_width = max(width - 2, 20)
    lines: list[str] = []

    if title:
        clean_title = re.sub(r"\[.*?\]", "", title)
        title_len = len(clean_title)
        dash_count = max(inner_width - title_len - 4, 2)
        top = f"[{border_style}]┌──[/{border_style}] [{title_style}]{title}[/{title_style}] [{border_style}]{'─' * dash_count}┐[/{border_style}]"
    else:
        top = f"[{border_style}]┌{'─' * inner_width}┐[/{border_style}]"
    lines.append(top)

    if content is not None:
        if isinstance(content, str):
            body = content.splitlines()
        else:
            body = list(content)
        for line in body:
            lines.append(f"[{border_style}]│[/{border_style}] {line}")

    bottom = f"[{border_style}]└{'─' * inner_width}┘[/{border_style}]"
    lines.append(bottom)
    return "\n".join(lines)


# -- Themes -----------------------------------------------------------------

THEMES: dict[str, dict[str, str]] = {
    "default": {"user_prefix_rich": "bold green", "user_prefix_pt": "ansigreen"},
    "dark":    {"user_prefix_rich": "bold cyan",  "user_prefix_pt": "ansicyan"},
    "light":   {"user_prefix_rich": "bold blue",  "user_prefix_pt": "ansiblue"},
    "minimal": {"user_prefix_rich": "green",      "user_prefix_pt": "ansigreen"},
}
DEFAULT_THEME = "default"


def theme_names() -> list[str]:
    return list(THEMES)


def get_theme(name: str | None = None) -> dict[str, str]:
    return THEMES.get(name or DEFAULT_THEME, THEMES[DEFAULT_THEME])
