"""Design tokens for hund.ui.

16-ANSI-safe i chrome och statushierarki (PowerShell, iTerm, Terminal.app,
Windows Terminal). Hunds svarstext använder användarbeslutad Bone White
(truecolor) där terminalen stödjer det. Inga emojis (CLAUDE.md).

Tier-farger enligt beslut:
  Master=gold->bright_yellow, Expert=silver->white, Adept=bla->cyan,
  Apprentice=gron->green, Novice=gra->dim.
"""
from __future__ import annotations

EMDASH = "—"  # tier saknar varde (se stats.tiers.build_stat)

# Rich-fargnamn (16-ANSI) - for Rich-utskrifter.
TIER_RICH: dict[str, str] = {
    "Novice": "dim",
    "Apprentice": "green",
    "Adept": "cyan",
    "Expert": "white",
    "Master": "bright_yellow",
    EMDASH: "dim",
}

# Prompt Toolkit-fargnamn (ansi*) - for bottom_toolbar.
TIER_PT: dict[str, str] = {
    "Novice": "ansibrightblack",
    "Apprentice": "ansigreen",
    "Adept": "ansicyan",
    "Expert": "ansiwhite",
    "Master": "ansibrightyellow",
    EMDASH: "ansibrightblack",
}

# Separering - vem sager vad (plan §1.3). Inga emojis.
USER_PREFIX = "du>"
USER_PREFIX_RICH = "bold green"
HUND_INDENT = "  "
SYSTEM_BULLET = "*"
SEPARATOR_CHAR = "─"  # box-drawing (tillaten, ej emoji)

# Hund body-text farg. Customization: Bone White (#E3E3E4), inte #FFFFFF.
HUND_FG = "#E3E3E4"

STAT_ABBR: dict[str, str] = {
    "clarity": "CLR",
    "precision": "PRC",
    "efficiency": "EFF",
    "endurance": "END",
    "mastery": "MAS",
}
STAT_ORDER: list[str] = ["clarity", "precision", "efficiency", "endurance", "mastery"]

BAR_FILL = "█"   # full block
BAR_EMPTY = "░"  # light shade
BAR_WIDTH = 8


def tier_rich(tier: str | None) -> str:
    return TIER_RICH.get(tier or "", "dim")


def tier_pt(tier: str | None) -> str:
    return TIER_PT.get(tier or "", "ansibrightblack")


# -- Teman (P3 /theme) -----------------------------------------------------
# 16-ANSI-safe user-prefix-farg per tema. pavisa live-prompt-prefix.
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
