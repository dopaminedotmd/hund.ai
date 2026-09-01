"""Design tokens and visual styling for hund.ui.

Unified token architecture: Truecolor (hex) with 16-ANSI fallback for standard
terminals. Rounded response/modal drawing (╭─╮, │, ╰─╯), block progress bars,
and strict zero-emoji invariants.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any

from prompt_toolkit.styles import Style


def supports_truecolor() -> bool:
    """Check if the terminal environment supports 24-bit truecolor (hex colors)."""
    if "NO_COLOR" in os.environ:
        return False
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        return True
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    if term_program in ("iterm.app", "wezterm", "vscode", "alacritty", "ghostty", "hyper", "mintty"):
        return True
    if os.environ.get("WT_SESSION"):  # Windows Terminal
        return True
    if sys.platform == "win32":
        return True
    return False


# -- Hund signature skin ---------------------------------------------------

SKINS: dict[str, dict[str, Any]] = {
    "marshmallow": {
        "name": "marshmallow",
        "pygments": "one-dark",
        "tokens": {
            "primary": "#FFFFFF",
            "secondary": "#7E889B",
            "accent": "#4EBCD5",
            "meta_accent": "#D896C7",
            "logo": "#FFFFFF",
            "user": "#50FA7B",
            "success": "#50FA7B",
            "warning": "#F1FA8C",
            "danger": "#FF5555",
            "tool": "#C792EA",
            "thinking": "#7DC8D8",
            "learning": "#E6C07B",
            "growth_gold": "#E6C07B",
            "growth_cream": "#F0E6D2",
            "growth_ochre": "#D19A66",
            "growth_brass": "#C8A96B",
            "skill_seed": "#A985B3",
            "add": "#78B88A",
            "del": "#E07A82",
            "add_bg": "#1E3A2B",
            "add_fg": "#8FBF9F",
            "del_bg": "#3D1E24",
            "del_fg": "#C97B84",
            "diff_tree": "#6B7280",
            "diff_lineno": "#555E68",
            "diff_file_header": "#E5E7EB",
            "mascot": "#FFFFFF",
            "mascot_status": "#959EAE",
            "modal_footer": "#A2ABC0",
        },
        "ansi": {
            "primary": "ansiwhite",
            "secondary": "ansibrightblack",
            "accent": "ansicyan",
            "meta_accent": "ansibrightmagenta",
            "logo": "ansiwhite",
            "user": "ansigreen",
            "success": "ansigreen",
            "warning": "ansibrightyellow",
            "danger": "ansired",
            "tool": "ansimagenta",
            "thinking": "ansibrightcyan",
            "learning": "ansiyellow",
            "growth_gold": "ansiyellow",
            "growth_ochre": "ansibrightyellow",
            "growth_brass": "ansiyellow",
            "skill_seed": "ansimagenta",
            "add": "ansigreen",
            "del": "ansired",
            "mascot": "ansiwhite",
        },
    },
}

DEFAULT_SKIN = "marshmallow"
DEFAULT_THEME = DEFAULT_SKIN
THEMES = SKINS  # Alias for backward compatibility

# Code-level compatibility only.
SKINS["bone"] = SKINS["marshmallow"]

PYGMENTS_THEMES: dict[str, str] = {
    "marshmallow": "one-dark",
    "bone": "one-dark",
}


def get_pygments_theme(skin_name: str | None = None) -> str:
    """Get the corresponding Pygments syntax highlighting theme name for a skin."""
    return "one-dark"


def get_skin(name: str | None = None) -> dict[str, Any]:
    """Retrieve skin definition by name with fallback to DEFAULT_SKIN."""
    return SKINS["marshmallow"]


def get_theme(name: str | None = None) -> dict[str, Any]:
    """Backward compatibility alias for get_skin."""
    return get_skin(name)


def theme_names() -> list[str]:
    """List all available skin names."""
    return ["marshmallow"]


def make_pt_style(skin_name: str | None = None) -> Style:
    """Construct a prompt_toolkit Style object tailored for the specified skin."""
    skin = get_skin(skin_name)
    tokens = skin["tokens"]
    add_style = f"bg:{tokens.get('add_bg', '#1E3A2B')}"
    del_style = f"bg:{tokens.get('del_bg', '#3D1E24')}"
    base_style = Style.from_dict(
        {
            "": tokens["primary"],
            "primary": tokens["primary"],
            "secondary": tokens["secondary"],
            "dim": tokens["secondary"],
            "backdrop": "#545B6B",
            "selected": "bg:#FFFFFF fg:#000000 bold",
            "selection": "bg:#FFFFFF fg:#000000 bold",
            "accent": tokens["accent"],
            "meta_accent": "bold " + tokens["meta_accent"],
            "meta-accent": "bold " + tokens["meta_accent"],
            "success": tokens["success"],
            "danger": tokens["danger"],
            "warning": tokens["warning"],
            "tool": tokens["tool"],
            "thinking": tokens["thinking"],
            "learning": tokens["learning"],
            "growth_gold": tokens["growth_gold"],
            "growth_cream": tokens.get("growth_cream", "#F0E6D2"),
            "growth_ochre": tokens["growth_ochre"],
            "growth_brass": "bold " + tokens["growth_brass"],
            "skill_seed": tokens["skill_seed"],
            "add": add_style,
            "del": del_style,
            "diff_tree": tokens["diff_tree"],
            "diff_lineno": tokens["diff_lineno"],
            "diff_file_header": tokens["diff_file_header"],
            "mascot": tokens["mascot"],
            "logo": "bold " + tokens.get("logo", "#FFFFFF"),
            "user": tokens["user"],
            "prompt": "bold " + tokens["user"],
            "status": tokens["secondary"],
            "header": "bold " + tokens["accent"],
            "number": "bold " + tokens["meta_accent"],
            "bullet": "bold " + tokens["accent"],
            "label": "bold " + tokens["meta_accent"],
            "code": tokens["tool"],
            "completion-menu": "noinherit bg:default noreverse fg:" + tokens["primary"],
            "completion-menu.completion": "noinherit bg:default noreverse fg:" + tokens["accent"],
            "completion-menu.completion.current": "noinherit bg:default noreverse bold fg:" + tokens["accent"],
            "completion-menu.meta.completion": "noinherit bg:default noreverse fg:" + tokens["secondary"],
            "completion-menu.meta.completion.current": "noinherit bg:default noreverse fg:" + tokens["primary"],
            "scrollbar.background": "bg:ansiblack",
            "scrollbar.button": "bg:" + tokens["secondary"],
            "modal_footer": tokens.get("modal_footer", "#A2ABC0"),
            "modal-footer": tokens.get("modal_footer", "#A2ABC0"),
        }
    )

    try:
        from prompt_toolkit.styles import merge_styles
        from prompt_toolkit.styles.pygments import style_from_pygments_cls
        from pygments.styles import get_style_by_name

        pyg_theme = get_pygments_theme(skin_name)
        pyg_cls = get_style_by_name(pyg_theme)
        return merge_styles([base_style, style_from_pygments_cls(pyg_cls)])
    except Exception:
        return base_style


# -- Core Design Tokens (Hex + 16-ANSI fallback) ---------------------------
COLOR_TOKENS: dict[str, dict[str, str]] = {
    "text":     {"hex": "#E3E3E4", "rich": "white",          "pt": "ansiwhite"},
    "dim":      {"hex": "#7E889B", "rich": "bright_black",   "pt": "ansibrightblack"},
    "cyan":     {"hex": "#4EBCD5", "rich": "cyan",           "pt": "ansicyan"},
    "green":    {"hex": "#50FA7B", "rich": "green",          "pt": "ansigreen"},
    "yellow":   {"hex": "#F1FA8C", "rich": "bright_yellow",   "pt": "ansibrightyellow"},
    "red":      {"hex": "#FF5555", "rich": "red",            "pt": "ansired"},
    "thinking": {"hex": "#7DC8D8", "rich": "bright_cyan",    "pt": "ansibrightcyan"},
    "learning": {"hex": "#E6C07B", "rich": "yellow",         "pt": "ansiyellow"},
    "tool":     {"hex": "#C792EA", "rich": "magenta",        "pt": "ansimagenta"},
    "modal_footer": {"hex": "#A2ABC0", "rich": "bright_black", "pt": "ansibrightblack"},
}

HUND_TEXT = "#E3E3E4"    # Primary bone white text
HUND_DIM = "#7E889B"     # Muted structural borders & metadata
HUND_CYAN = "#4EBCD5"    # Accent / Hund identity
HUND_GREEN = "#50FA7B"   # User prompt & positive confirmation
HUND_YELLOW = "#F1FA8C"  # Master prestige / warnings
HUND_RED = "#FF5555"     # Danger / blocked actions

HUND_FG = HUND_TEXT

# Semantic tokens (spec: semantic name -> color). Used by the TUI lexer/style.
# Never hardcode raw colors in agent logic — reference these names.
SEMANTIC: dict[str, str] = {
    "primary": HUND_TEXT,      # AI voice — highest contrast
    "secondary": HUND_DIM,     # system/status, borders, dividers
    "accent": HUND_CYAN,       # paths, arrows, references
    "success": HUND_GREEN,     # confirmations, diff-add
    "danger": HUND_RED,        # errors, diff-remove, blocked
    "warning": HUND_YELLOW,    # permissions, warnings
    "tool": "#C792EA",         # tool calls (purple)
    "user": HUND_GREEN,        # user input
    "thinking": "#7DC8D8",     # thinking phrase
    "learning": "#E6C07B",     # reflection & XP
    "add": "#50FA7B",          # diff additions
    "del": "#FF5555",          # diff deletions
    "mascot": "#E3E3E4",       # mascot neutral color
}

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
USER_PREFIX = "❯"
USER_PREFIX_RICH = "bold green"
HUND_INDENT = "  "
HUND_RAIL = "│ "
SYSTEM_BULLET = "•"
SEPARATOR_CHAR = "─"


HUND_ASCII_COMPACT = (
    "        ░░    ░░░░\n"
    "        ░░░░░░░░\n"
    "        ░░██░░██░░\n"
    "        ░░░░░░░░░░██\n"
    "░░    ░░░░░░░░░░░░\n"
    "░░  ░░░░░░░░░░░░\n"
    "░░  ░░░░░░░░░░░░\n"
    "░░░░░░░░░░░░░░░░\n"
    "  ░░░░░░  ░░  ░░"
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
