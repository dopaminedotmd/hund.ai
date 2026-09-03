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
            "secondary": "#9AA5B8",
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
            "interim_text": "#A2ABC0",
            "interim_border": "#4B5563",
            "diff_stat_add": "#50FA7B",
            "diff_stat_del": "#FF5555",
            "add": "#78B88A",
            "del": "#E07A82",
            "add_bg": "#1e2b22",
            "add_fg": "#8FBF9F",
            "del_bg": "#3d1e24",
            "del_fg": "#C97B84",
            "diff_tree": "#6B7280",
            "diff_lineno": "#555E68",
            "diff_file_header": "#E5E7EB",
            "mascot": "#FFFFFF",
            "mascot_status": "#959EAE",
            "modal_footer": "#A2ABC0",
            "syntax_keyword": "#5BE5F8",
            "syntax_string": "#50FA7B",
            "syntax_number": "#E599D6",
            "syntax_comment": "#6E7B90",
            "syntax_function": "#F5CF75",
            "syntax_operator": "#7DD8EB",
            "syntax_variable": "#C5D0E0",
            "syntax_diff_tag": "#5BE5F8",
            "syntax_diff_attr": "#E6C07B",
            "syntax_diff_string": "#8FBF9F",
            "syntax_diff_text": "#E5E7EB",
            "syntax_diff_keyword": "#5BE5F8",
            "syntax_diff_number": "#E599D6",
            "syntax_diff_comment": "#6E7B90",
            "syntax_diff_function": "#F5CF75",
            "syntax_diff_operator": "#7DD8EB",
            "syntax_diff_variable": "#C5D0E0",
            "syntax_del_keyword": "#A86872",
            "syntax_del_string": "#907870",
            "syntax_del_number": "#9C6880",
            "syntax_del_comment": "#684850",
            "syntax_del_function": "#A07870",
            "syntax_del_operator": "#885860",
            "syntax_del_variable": "#A87A82",
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
            "growth_cream": "ansiwhite",
            "growth_ochre": "ansibrightyellow",
            "growth_brass": "ansiyellow",
            "skill_seed": "ansimagenta",
            "interim_text": "ansibrightblack",
            "interim_border": "ansibrightblack",
            "diff_stat_add": "ansigreen",
            "diff_stat_del": "ansired",
            "add": "ansigreen",
            "del": "ansired",
            "add_bg": "ansiblack",
            "add_fg": "ansigreen",
            "del_bg": "ansiblack",
            "del_fg": "ansired",
            "diff_tree": "ansibrightblack",
            "diff_lineno": "ansibrightblack",
            "diff_file_header": "ansiwhite",
            "mascot": "ansiwhite",
            "mascot_status": "ansibrightblack",
            "modal_footer": "ansibrightblack",
            "syntax_keyword": "ansicyan",
            "syntax_string": "ansigreen",
            "syntax_number": "ansibrightmagenta",
            "syntax_comment": "ansibrightblack",
            "syntax_function": "ansiyellow",
            "syntax_operator": "ansicyan",
            "syntax_variable": "ansibrightblack",
            "syntax_diff_tag": "ansicyan",
            "syntax_diff_attr": "ansiyellow",
            "syntax_diff_string": "ansigreen",
            "syntax_diff_text": "ansiwhite",
            "syntax_diff_keyword": "ansicyan",
            "syntax_diff_number": "ansibrightmagenta",
            "syntax_diff_comment": "ansibrightblack",
            "syntax_diff_function": "ansiyellow",
            "syntax_diff_operator": "ansicyan",
            "syntax_diff_variable": "ansibrightblack",
            "syntax_del_keyword": "ansired",
            "syntax_del_string": "ansibrightblack",
            "syntax_del_number": "ansimagenta",
            "syntax_del_comment": "ansibrightblack",
            "syntax_del_function": "ansired",
            "syntax_del_operator": "ansired",
            "syntax_del_variable": "ansired",
        },
    },
    "dracula": {
        "name": "dracula",
        "pygments": "one-dark",
        "tokens": {
            "primary": "#F8F8F2",
            "secondary": "#6272A4",
            "accent": "#BD93F9",
            "meta_accent": "#FF79C6",
            "logo": "#F8F8F2",
            "user": "#50FA7B",
            "success": "#50FA7B",
            "warning": "#F1FA8C",
            "danger": "#FF5555",
            "tool": "#BD93F9",
            "thinking": "#8BE9FD",
            "learning": "#FFB86C",
            "growth_gold": "#F1FA8C",
            "growth_cream": "#F8F8F2",
            "growth_ochre": "#FFB86C",
            "growth_brass": "#E2C07D",
            "skill_seed": "#FF79C6",
            "interim_text": "#A2ABC0",
            "interim_border": "#6272A4",
            "diff_stat_add": "#50FA7B",
            "diff_stat_del": "#FF5555",
            "add": "#50FA7B",
            "del": "#FF5555",
            "add_bg": "#1B2B22",
            "add_fg": "#50FA7B",
            "del_bg": "#3E1F28",
            "del_fg": "#FF5555",
            "diff_tree": "#6272A4",
            "diff_lineno": "#44475A",
            "diff_file_header": "#F8F8F2",
            "mascot": "#F8F8F2",
            "mascot_status": "#6272A4",
            "modal_footer": "#6272A4",
            "syntax_keyword": "#FF79C6",
            "syntax_string": "#F1FA8C",
            "syntax_number": "#BD93F9",
            "syntax_comment": "#6272A4",
            "syntax_function": "#50FA7B",
            "syntax_operator": "#FF79C6",
            "syntax_variable": "#8BE9FD",
            "syntax_diff_tag": "#8BE9FD",
            "syntax_diff_attr": "#F1FA8C",
            "syntax_diff_string": "#50FA7B",
            "syntax_diff_text": "#F8F8F2",
            "syntax_diff_keyword": "#BD93F9",
            "syntax_diff_number": "#BD93F9",
            "syntax_diff_comment": "#6272A4",
            "syntax_diff_function": "#50FA7B",
            "syntax_diff_operator": "#8BE9FD",
            "syntax_diff_variable": "#F8F8F2",
            "syntax_del_keyword": "#A85870",
            "syntax_del_string": "#987868",
            "syntax_del_number": "#986890",
            "syntax_del_comment": "#504058",
            "syntax_del_function": "#889870",
            "syntax_del_operator": "#885068",
            "syntax_del_variable": "#A87080",
        },
        "ansi": {
            "primary": "ansiwhite",
            "secondary": "ansibrightblack",
            "accent": "ansibrightmagenta",
            "meta_accent": "ansimagenta",
            "logo": "ansiwhite",
            "user": "ansigreen",
            "success": "ansigreen",
            "warning": "ansibrightyellow",
            "danger": "ansired",
            "tool": "ansibrightmagenta",
            "thinking": "ansicyan",
            "learning": "ansiyellow",
            "growth_gold": "ansiyellow",
            "growth_cream": "ansiwhite",
            "growth_ochre": "ansiyellow",
            "growth_brass": "ansiyellow",
            "skill_seed": "ansimagenta",
            "interim_text": "ansibrightblack",
            "interim_border": "ansibrightblack",
            "diff_stat_add": "ansigreen",
            "diff_stat_del": "ansired",
            "add": "ansigreen",
            "del": "ansired",
            "add_bg": "ansiblack",
            "add_fg": "ansigreen",
            "del_bg": "ansiblack",
            "del_fg": "ansired",
            "diff_tree": "ansibrightblack",
            "diff_lineno": "ansibrightblack",
            "diff_file_header": "ansiwhite",
            "mascot": "ansiwhite",
            "mascot_status": "ansibrightblack",
            "modal_footer": "ansibrightblack",
            "syntax_keyword": "ansimagenta",
            "syntax_string": "ansiyellow",
            "syntax_number": "ansibrightmagenta",
            "syntax_comment": "ansibrightblack",
            "syntax_function": "ansigreen",
            "syntax_operator": "ansimagenta",
            "syntax_variable": "ansicyan",
            "syntax_diff_tag": "ansicyan",
            "syntax_diff_attr": "ansiyellow",
            "syntax_diff_string": "ansigreen",
            "syntax_diff_text": "ansiwhite",
            "syntax_diff_keyword": "ansimagenta",
            "syntax_diff_number": "ansibrightmagenta",
            "syntax_diff_comment": "ansibrightblack",
            "syntax_diff_function": "ansigreen",
            "syntax_diff_operator": "ansicyan",
            "syntax_diff_variable": "ansiwhite",
            "syntax_del_keyword": "ansired",
            "syntax_del_string": "ansibrightblack",
            "syntax_del_number": "ansimagenta",
            "syntax_del_comment": "ansibrightblack",
            "syntax_del_function": "ansired",
            "syntax_del_operator": "ansired",
            "syntax_del_variable": "ansired",
        },
    },
    "tokyonight": {
        "name": "tokyonight",
        "pygments": "one-dark",
        "tokens": {
            "primary": "#C0CAF5",
            "secondary": "#565F89",
            "accent": "#7AA2F7",
            "meta_accent": "#BB9AF7",
            "logo": "#C0CAF5",
            "user": "#9ECE6A",
            "success": "#9ECE6A",
            "warning": "#E0AF68",
            "danger": "#F7768E",
            "tool": "#BB9AF7",
            "thinking": "#7DCFFF",
            "learning": "#FF9E64",
            "growth_gold": "#E0AF68",
            "growth_cream": "#C0CAF5",
            "growth_ochre": "#FF9E64",
            "growth_brass": "#C8A96B",
            "skill_seed": "#9D7CD8",
            "interim_text": "#A2ABC0",
            "interim_border": "#565F89",
            "diff_stat_add": "#9ECE6A",
            "diff_stat_del": "#F7768E",
            "add": "#9ECE6A",
            "del": "#F7768E",
            "add_bg": "#192922",
            "add_fg": "#9ECE6A",
            "del_bg": "#3A1B28",
            "del_fg": "#F7768E",
            "diff_tree": "#565F89",
            "diff_lineno": "#414868",
            "diff_file_header": "#C0CAF5",
            "mascot": "#C0CAF5",
            "mascot_status": "#565F89",
            "modal_footer": "#565F89",
            "syntax_keyword": "#BB9AF7",
            "syntax_string": "#9ECE6A",
            "syntax_number": "#FF9E64",
            "syntax_comment": "#565F89",
            "syntax_function": "#7AA2F7",
            "syntax_operator": "#89DDFF",
            "syntax_variable": "#A9B1D6",
            "syntax_diff_tag": "#7DCFFF",
            "syntax_diff_attr": "#E0AF68",
            "syntax_diff_string": "#9ECE6A",
            "syntax_diff_text": "#C0CAF5",
            "syntax_diff_keyword": "#BB9AF7",
            "syntax_diff_number": "#FF9E64",
            "syntax_diff_comment": "#565F89",
            "syntax_diff_function": "#7AA2F7",
            "syntax_diff_operator": "#89DDFF",
            "syntax_diff_variable": "#A9B1D6",
            "syntax_del_keyword": "#A06888",
            "syntax_del_string": "#888068",
            "syntax_del_number": "#A06858",
            "syntax_del_comment": "#484058",
            "syntax_del_function": "#706890",
            "syntax_del_operator": "#6888A0",
            "syntax_del_variable": "#987080",
        },
        "ansi": {
            "primary": "ansiwhite",
            "secondary": "ansibrightblack",
            "accent": "ansiblue",
            "meta_accent": "ansimagenta",
            "logo": "ansiwhite",
            "user": "ansigreen",
            "success": "ansigreen",
            "warning": "ansiyellow",
            "danger": "ansired",
            "tool": "ansimagenta",
            "thinking": "ansicyan",
            "learning": "ansibrightyellow",
            "growth_gold": "ansiyellow",
            "growth_cream": "ansiwhite",
            "growth_ochre": "ansiyellow",
            "growth_brass": "ansiyellow",
            "skill_seed": "ansimagenta",
            "interim_text": "ansibrightblack",
            "interim_border": "ansibrightblack",
            "diff_stat_add": "ansigreen",
            "diff_stat_del": "ansired",
            "add": "ansigreen",
            "del": "ansired",
            "add_bg": "ansiblack",
            "add_fg": "ansigreen",
            "del_bg": "ansiblack",
            "del_fg": "ansired",
            "diff_tree": "ansibrightblack",
            "diff_lineno": "ansibrightblack",
            "diff_file_header": "ansiwhite",
            "mascot": "ansiwhite",
            "mascot_status": "ansibrightblack",
            "modal_footer": "ansibrightblack",
            "syntax_keyword": "ansimagenta",
            "syntax_string": "ansigreen",
            "syntax_number": "ansibrightyellow",
            "syntax_comment": "ansibrightblack",
            "syntax_function": "ansiblue",
            "syntax_operator": "ansicyan",
            "syntax_variable": "ansibrightblack",
            "syntax_diff_tag": "ansicyan",
            "syntax_diff_attr": "ansiyellow",
            "syntax_diff_string": "ansigreen",
            "syntax_diff_text": "ansiwhite",
            "syntax_diff_keyword": "ansimagenta",
            "syntax_diff_number": "ansibrightyellow",
            "syntax_diff_comment": "ansibrightblack",
            "syntax_diff_function": "ansiblue",
            "syntax_diff_operator": "ansicyan",
            "syntax_diff_variable": "ansiwhite",
            "syntax_del_keyword": "ansired",
            "syntax_del_string": "ansibrightblack",
            "syntax_del_number": "ansimagenta",
            "syntax_del_comment": "ansibrightblack",
            "syntax_del_function": "ansired",
            "syntax_del_operator": "ansired",
            "syntax_del_variable": "ansired",
        },
    },
    "nord": {
        "name": "nord",
        "pygments": "one-dark",
        "tokens": {
            "primary": "#ECEFF4",
            "secondary": "#4C566A",
            "accent": "#88C0D0",
            "meta_accent": "#B48EAD",
            "logo": "#ECEFF4",
            "user": "#A3BE8C",
            "success": "#A3BE8C",
            "warning": "#EBCB8B",
            "danger": "#BF616A",
            "tool": "#81A1C1",
            "thinking": "#8FBCBB",
            "learning": "#EBCB8B",
            "growth_gold": "#EBCB8B",
            "growth_cream": "#E5E9F0",
            "growth_ochre": "#D08770",
            "growth_brass": "#C8A96B",
            "skill_seed": "#B48EAD",
            "interim_text": "#A2ABC0",
            "interim_border": "#4C566A",
            "diff_stat_add": "#A3BE8C",
            "diff_stat_del": "#BF616A",
            "add": "#A3BE8C",
            "del": "#BF616A",
            "add_bg": "#202F28",
            "add_fg": "#A3BE8C",
            "del_bg": "#3B2228",
            "del_fg": "#BF616A",
            "diff_tree": "#4C566A",
            "diff_lineno": "#434C5E",
            "diff_file_header": "#ECEFF4",
            "mascot": "#ECEFF4",
            "mascot_status": "#4C566A",
            "modal_footer": "#4C566A",
            "syntax_keyword": "#81A1C1",
            "syntax_string": "#A3BE8C",
            "syntax_number": "#B48EAD",
            "syntax_comment": "#4C566A",
            "syntax_function": "#88C0D0",
            "syntax_operator": "#81A1C1",
            "syntax_variable": "#D8DEE9",
            "syntax_diff_tag": "#88C0D0",
            "syntax_diff_attr": "#EBCB8B",
            "syntax_diff_string": "#A3BE8C",
            "syntax_diff_text": "#ECEFF4",
            "syntax_diff_keyword": "#81A1C1",
            "syntax_diff_number": "#B48EAD",
            "syntax_diff_comment": "#4C566A",
            "syntax_diff_function": "#88C0D0",
            "syntax_diff_operator": "#81A1C1",
            "syntax_diff_variable": "#D8DEE9",
            "syntax_del_keyword": "#906870",
            "syntax_del_string": "#807868",
            "syntax_del_number": "#886880",
            "syntax_del_comment": "#403840",
            "syntax_del_function": "#787880",
            "syntax_del_operator": "#706068",
            "syntax_del_variable": "#887078",
        },
        "ansi": {
            "primary": "ansiwhite",
            "secondary": "ansibrightblack",
            "accent": "ansicyan",
            "meta_accent": "ansimagenta",
            "logo": "ansiwhite",
            "user": "ansigreen",
            "success": "ansigreen",
            "warning": "ansiyellow",
            "danger": "ansired",
            "tool": "ansiblue",
            "thinking": "ansicyan",
            "learning": "ansiyellow",
            "growth_gold": "ansiyellow",
            "growth_cream": "ansiwhite",
            "growth_ochre": "ansiyellow",
            "growth_brass": "ansiyellow",
            "skill_seed": "ansimagenta",
            "interim_text": "ansibrightblack",
            "interim_border": "ansibrightblack",
            "diff_stat_add": "ansigreen",
            "diff_stat_del": "ansired",
            "add": "ansigreen",
            "del": "ansired",
            "add_bg": "ansiblack",
            "add_fg": "ansigreen",
            "del_bg": "ansiblack",
            "del_fg": "ansired",
            "diff_tree": "ansibrightblack",
            "diff_lineno": "ansibrightblack",
            "diff_file_header": "ansiwhite",
            "mascot": "ansiwhite",
            "mascot_status": "ansibrightblack",
            "modal_footer": "ansibrightblack",
            "syntax_keyword": "ansiblue",
            "syntax_string": "ansigreen",
            "syntax_number": "ansimagenta",
            "syntax_comment": "ansibrightblack",
            "syntax_function": "ansicyan",
            "syntax_operator": "ansiblue",
            "syntax_variable": "ansibrightblack",
            "syntax_diff_tag": "ansicyan",
            "syntax_diff_attr": "ansiyellow",
            "syntax_diff_string": "ansigreen",
            "syntax_diff_text": "ansiwhite",
            "syntax_diff_keyword": "ansiblue",
            "syntax_diff_number": "ansimagenta",
            "syntax_diff_comment": "ansibrightblack",
            "syntax_diff_function": "ansicyan",
            "syntax_diff_operator": "ansiblue",
            "syntax_diff_variable": "ansiwhite",
            "syntax_del_keyword": "ansired",
            "syntax_del_string": "ansibrightblack",
            "syntax_del_number": "ansimagenta",
            "syntax_del_comment": "ansibrightblack",
            "syntax_del_function": "ansired",
            "syntax_del_operator": "ansired",
            "syntax_del_variable": "ansired",
        },
    },
    "monokai": {
        "name": "monokai",
        "pygments": "one-dark",
        "tokens": {
            "primary": "#F8F8F2",
            "secondary": "#75715E",
            "accent": "#66D9EF",
            "meta_accent": "#F92672",
            "logo": "#F8F8F2",
            "user": "#A6E22E",
            "success": "#A6E22E",
            "warning": "#E6DB74",
            "danger": "#F92672",
            "tool": "#AE81FF",
            "thinking": "#66D9EF",
            "learning": "#FD971F",
            "growth_gold": "#E6DB74",
            "growth_cream": "#F8F8F2",
            "growth_ochre": "#FD971F",
            "growth_brass": "#C8A96B",
            "skill_seed": "#AE81FF",
            "interim_text": "#A2ABC0",
            "interim_border": "#75715E",
            "diff_stat_add": "#A6E22E",
            "diff_stat_del": "#F92672",
            "add": "#A6E22E",
            "del": "#F92672",
            "add_bg": "#1E2C1A",
            "add_fg": "#A6E22E",
            "del_bg": "#3D1A26",
            "del_fg": "#F92672",
            "diff_tree": "#75715E",
            "diff_lineno": "#49483E",
            "diff_file_header": "#F8F8F2",
            "mascot": "#F8F8F2",
            "mascot_status": "#75715E",
            "modal_footer": "#75715E",
            "syntax_keyword": "#F92672",
            "syntax_string": "#E6DB74",
            "syntax_number": "#AE81FF",
            "syntax_comment": "#75715E",
            "syntax_function": "#A6E22E",
            "syntax_operator": "#F92672",
            "syntax_variable": "#FD971F",
            "syntax_diff_tag": "#66D9EF",
            "syntax_diff_attr": "#E6DB74",
            "syntax_diff_string": "#A6E22E",
            "syntax_diff_text": "#F8F8F2",
            "syntax_diff_keyword": "#F92672",
            "syntax_diff_number": "#AE81FF",
            "syntax_diff_comment": "#75715E",
            "syntax_diff_function": "#A6E22E",
            "syntax_diff_operator": "#66D9EF",
            "syntax_diff_variable": "#FD971F",
            "syntax_del_keyword": "#B04868",
            "syntax_del_string": "#988860",
            "syntax_del_number": "#8868B0",
            "syntax_del_comment": "#504838",
            "syntax_del_function": "#809858",
            "syntax_del_operator": "#984058",
            "syntax_del_variable": "#A07880",
        },
        "ansi": {
            "primary": "ansiwhite",
            "secondary": "ansibrightblack",
            "accent": "ansicyan",
            "meta_accent": "ansired",
            "logo": "ansiwhite",
            "user": "ansigreen",
            "success": "ansigreen",
            "warning": "ansiyellow",
            "danger": "ansired",
            "tool": "ansimagenta",
            "thinking": "ansicyan",
            "learning": "ansibrightyellow",
            "growth_gold": "ansiyellow",
            "growth_cream": "ansiwhite",
            "growth_ochre": "ansiyellow",
            "growth_brass": "ansiyellow",
            "skill_seed": "ansimagenta",
            "interim_text": "ansibrightblack",
            "interim_border": "ansibrightblack",
            "diff_stat_add": "ansigreen",
            "diff_stat_del": "ansired",
            "add": "ansigreen",
            "del": "ansired",
            "add_bg": "ansiblack",
            "add_fg": "ansigreen",
            "del_bg": "ansiblack",
            "del_fg": "ansired",
            "diff_tree": "ansibrightblack",
            "diff_lineno": "ansibrightblack",
            "diff_file_header": "ansiwhite",
            "mascot": "ansiwhite",
            "mascot_status": "ansibrightblack",
            "modal_footer": "ansibrightblack",
            "syntax_keyword": "ansired",
            "syntax_string": "ansiyellow",
            "syntax_number": "ansimagenta",
            "syntax_comment": "ansibrightblack",
            "syntax_function": "ansigreen",
            "syntax_operator": "ansired",
            "syntax_variable": "ansibrightblack",
            "syntax_diff_tag": "ansicyan",
            "syntax_diff_attr": "ansiyellow",
            "syntax_diff_string": "ansigreen",
            "syntax_diff_text": "ansiwhite",
            "syntax_diff_keyword": "ansired",
            "syntax_diff_number": "ansimagenta",
            "syntax_diff_comment": "ansibrightblack",
            "syntax_diff_function": "ansigreen",
            "syntax_diff_operator": "ansicyan",
            "syntax_diff_variable": "ansiwhite",
            "syntax_del_keyword": "ansired",
            "syntax_del_string": "ansibrightblack",
            "syntax_del_number": "ansimagenta",
            "syntax_del_comment": "ansibrightblack",
            "syntax_del_function": "ansired",
            "syntax_del_operator": "ansired",
            "syntax_del_variable": "ansired",
        },
    },
    "gruvbox": {
        "name": "gruvbox",
        "pygments": "one-dark",
        "tokens": {
            "primary": "#EBDBB2",
            "secondary": "#928374",
            "accent": "#83A598",
            "meta_accent": "#D3869B",
            "logo": "#EBDBB2",
            "user": "#B8BB26",
            "success": "#B8BB26",
            "warning": "#FABD2F",
            "danger": "#FB4934",
            "tool": "#D3869B",
            "thinking": "#8EC07C",
            "learning": "#FABD2F",
            "growth_gold": "#FABD2F",
            "growth_cream": "#EBDBB2",
            "growth_ochre": "#FE8019",
            "growth_brass": "#D79921",
            "skill_seed": "#D3869B",
            "interim_text": "#A2ABC0",
            "interim_border": "#928374",
            "diff_stat_add": "#B8BB26",
            "diff_stat_del": "#FB4934",
            "add": "#B8BB26",
            "del": "#FB4934",
            "add_bg": "#222C1A",
            "add_fg": "#B8BB26",
            "del_bg": "#3A1E20",
            "del_fg": "#FB4934",
            "diff_tree": "#928374",
            "diff_lineno": "#504945",
            "diff_file_header": "#EBDBB2",
            "mascot": "#EBDBB2",
            "mascot_status": "#928374",
            "modal_footer": "#928374",
            "syntax_keyword": "#FB4934",
            "syntax_string": "#B8BB26",
            "syntax_number": "#D3869B",
            "syntax_comment": "#928374",
            "syntax_function": "#FABD2F",
            "syntax_operator": "#8EC07C",
            "syntax_variable": "#EBDBB2",
            "syntax_diff_tag": "#83A598",
            "syntax_diff_attr": "#FABD2F",
            "syntax_diff_string": "#B8BB26",
            "syntax_diff_text": "#EBDBB2",
            "syntax_diff_keyword": "#FB4934",
            "syntax_diff_number": "#D3869B",
            "syntax_diff_comment": "#928374",
            "syntax_diff_function": "#FABD2F",
            "syntax_diff_operator": "#8EC07C",
            "syntax_diff_variable": "#EBDBB2",
            "syntax_del_keyword": "#A84840",
            "syntax_del_string": "#887850",
            "syntax_del_number": "#986070",
            "syntax_del_comment": "#584840",
            "syntax_del_function": "#987850",
            "syntax_del_operator": "#687858",
            "syntax_del_variable": "#987068",
        },
        "ansi": {
            "primary": "ansiwhite",
            "secondary": "ansibrightblack",
            "accent": "ansicyan",
            "meta_accent": "ansimagenta",
            "logo": "ansiwhite",
            "user": "ansigreen",
            "success": "ansigreen",
            "warning": "ansiyellow",
            "danger": "ansired",
            "tool": "ansimagenta",
            "thinking": "ansicyan",
            "learning": "ansiyellow",
            "growth_gold": "ansiyellow",
            "growth_cream": "ansiwhite",
            "growth_ochre": "ansiyellow",
            "growth_brass": "ansiyellow",
            "skill_seed": "ansimagenta",
            "interim_text": "ansibrightblack",
            "interim_border": "ansibrightblack",
            "diff_stat_add": "ansigreen",
            "diff_stat_del": "ansired",
            "add": "ansigreen",
            "del": "ansired",
            "add_bg": "ansiblack",
            "add_fg": "ansigreen",
            "del_bg": "ansiblack",
            "del_fg": "ansired",
            "diff_tree": "ansibrightblack",
            "diff_lineno": "ansibrightblack",
            "diff_file_header": "ansiwhite",
            "mascot": "ansiwhite",
            "mascot_status": "ansibrightblack",
            "modal_footer": "ansibrightblack",
            "syntax_keyword": "ansired",
            "syntax_string": "ansigreen",
            "syntax_number": "ansimagenta",
            "syntax_comment": "ansibrightblack",
            "syntax_function": "ansiyellow",
            "syntax_operator": "ansicyan",
            "syntax_variable": "ansibrightblack",
            "syntax_diff_tag": "ansicyan",
            "syntax_diff_attr": "ansiyellow",
            "syntax_diff_string": "ansigreen",
            "syntax_diff_text": "ansiwhite",
            "syntax_diff_keyword": "ansired",
            "syntax_diff_number": "ansimagenta",
            "syntax_diff_comment": "ansibrightblack",
            "syntax_diff_function": "ansiyellow",
            "syntax_diff_operator": "ansicyan",
            "syntax_diff_variable": "ansiwhite",
            "syntax_del_keyword": "ansired",
            "syntax_del_string": "ansibrightblack",
            "syntax_del_number": "ansimagenta",
            "syntax_del_comment": "ansibrightblack",
            "syntax_del_function": "ansired",
            "syntax_del_operator": "ansired",
            "syntax_del_variable": "ansired",
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
    "dracula": "one-dark",
    "tokyonight": "one-dark",
    "nord": "one-dark",
    "monokai": "one-dark",
    "gruvbox": "one-dark",
}


def get_pygments_theme(skin_name: str | None = None) -> str:
    """Get the corresponding Pygments syntax highlighting theme name for a skin."""
    return "one-dark"


def get_skin(name: str | None = None) -> dict[str, Any]:
    """Retrieve skin definition by name with fallback to DEFAULT_SKIN."""
    if not name:
        return SKINS[DEFAULT_SKIN]
    cleaned = str(name).strip().lower().replace("-", "").replace("_", "")
    for k, v in SKINS.items():
        if k.lower().replace("-", "").replace("_", "") == cleaned:
            return v
    return SKINS[DEFAULT_SKIN]


def get_theme(name: str | None = None) -> dict[str, Any]:
    """Backward compatibility alias for get_skin."""
    return get_skin(name)


def theme_names() -> list[str]:
    """List all available skin names."""
    return [k for k in SKINS.keys() if k != "bone"]


def make_pt_style(skin_name: str | None = None) -> Style:
    """Construct a prompt_toolkit Style object tailored for the specified skin."""
    skin = get_skin(skin_name)
    tokens = skin["tokens"]
    add_style = f"nostrike bg:{tokens.get('add_bg', '#1E2B22')}"
    del_style = f"nostrike bg:{tokens.get('del_bg', '#3D1E24')}"
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
            "strike": "nostrike",
            "s": "nostrike",
            "interim_text": tokens.get("interim_text", "#A2ABC0"),
            "interim-text": tokens.get("interim_text", "#A2ABC0"),
            "interim_border": tokens.get("interim_border", "#4B5563"),
            "interim-border": tokens.get("interim_border", "#4B5563"),
            "diff_stat_add": tokens.get("diff_stat_add", "#50FA7B"),
            "diff-stat-add": tokens.get("diff_stat_add", "#50FA7B"),
            "diff_stat_del": tokens.get("diff_stat_del", "#FF5555"),
            "diff-stat-del": tokens.get("diff_stat_del", "#FF5555"),
            "diff_tree": tokens.get("diff_tree", "#6B7280"),
            "diff_lineno": tokens.get("diff_lineno", "#555E68"),
            "diff_file_header": tokens.get("diff_file_header", "#E5E7EB"),
            "del_fg": tokens.get("del_fg", "#C97B84"),
            "add_fg": tokens.get("add_fg", "#8FBF9F"),
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
            "syntax_keyword": tokens.get("syntax_keyword", tokens["accent"]),
            "syntax_string": tokens.get("syntax_string", tokens["learning"]),
            "syntax_number": tokens.get("syntax_number", tokens["meta_accent"]),
            "syntax_comment": tokens.get("syntax_comment", tokens["secondary"]),
            "syntax_function": tokens.get("syntax_function", tokens.get("primary", "#FFFFFF")),
            "syntax_operator": tokens.get("syntax_operator", tokens["accent"]),
            "syntax_variable": tokens.get("syntax_variable", tokens["primary"]),
            "syntax_diff_tag": tokens.get("syntax_diff_tag", "#5BE5F8"),
            "syntax_diff_attr": tokens.get("syntax_diff_attr", "#E6C07B"),
            "syntax_diff_string": tokens.get("syntax_diff_string", "#8FBF9F"),
            "syntax_diff_text": tokens.get("syntax_diff_text", "#E5E7EB"),
            "syntax_diff_keyword": tokens.get("syntax_diff_keyword", "#5BE5F8"),
            "syntax_diff_number": tokens.get("syntax_diff_number", "#E599D6"),
            "syntax_diff_comment": tokens.get("syntax_diff_comment", "#6E7B90"),
            "syntax_diff_function": tokens.get("syntax_diff_function", "#F5CF75"),
            "syntax_diff_operator": tokens.get("syntax_diff_operator", "#7DD8EB"),
            "syntax_diff_variable": tokens.get("syntax_diff_variable", "#C5D0E0"),
            "syntax-diff-tag": tokens.get("syntax_diff_tag", "#5BE5F8"),
            "syntax-diff-attr": tokens.get("syntax_diff_attr", "#E6C07B"),
            "syntax-diff-string": tokens.get("syntax_diff_string", "#8FBF9F"),
            "syntax-diff-text": tokens.get("syntax_diff_text", "#E5E7EB"),
            "syntax-diff-keyword": tokens.get("syntax_diff_keyword", "#5BE5F8"),
            "syntax-diff-number": tokens.get("syntax_diff_number", "#E599D6"),
            "syntax-diff-comment": tokens.get("syntax_diff_comment", "#6E7B90"),
            "syntax-diff-function": tokens.get("syntax_diff_function", "#F5CF75"),
            "syntax-diff-operator": tokens.get("syntax_diff_operator", "#7DD8EB"),
            "syntax-diff-variable": tokens.get("syntax_diff_variable", "#C5D0E0"),
            "syntax_del_keyword": tokens.get("syntax_del_keyword", tokens.get("del_fg", "#C97B84")),
            "syntax_del_string": tokens.get("syntax_del_string", "#A88088"),
            "syntax_del_number": tokens.get("syntax_del_number", "#B07888"),
            "syntax_del_comment": tokens.get("syntax_del_comment", "#785860"),
            "syntax_del_function": tokens.get("syntax_del_function", "#B88080"),
            "syntax_del_operator": tokens.get("syntax_del_operator", "#986870"),
            "syntax_del_variable": tokens.get("syntax_del_variable", "#A87A82"),
            "syntax-keyword": tokens.get("syntax_keyword", tokens["accent"]),
            "syntax-string": tokens.get("syntax_string", tokens["learning"]),
            "syntax-number": tokens.get("syntax_number", tokens["meta_accent"]),
            "syntax-comment": tokens.get("syntax_comment", tokens["secondary"]),
            "syntax-function": tokens.get("syntax_function", tokens.get("primary", "#FFFFFF")),
            "syntax-operator": tokens.get("syntax_operator", tokens["accent"]),
            "syntax-variable": tokens.get("syntax_variable", tokens["primary"]),
            "syntax-del-keyword": tokens.get("syntax_del_keyword", tokens.get("del_fg", "#C97B84")),
            "syntax-del-string": tokens.get("syntax_del_string", "#A88088"),
            "syntax-del-number": tokens.get("syntax_del_number", "#B07888"),
            "syntax-del-comment": tokens.get("syntax_del_comment", "#785860"),
            "syntax-del-function": tokens.get("syntax_del_function", "#B88080"),
            "syntax-del-operator": tokens.get("syntax_del_operator", "#986870"),
            "syntax-del-variable": tokens.get("syntax_del_variable", "#A87A82"),
            "completion-menu": "noinherit bg:default noreverse fg:" + tokens["primary"],
            "completion-menu.completion": "noinherit bg:default noreverse fg:" + tokens["accent"],
            "completion-menu.completion.current": "noinherit bg:default noreverse bold fg:" + tokens["accent"],
            "completion-menu.meta.completion": "noinherit bg:default noreverse fg:" + tokens["secondary"],
            "completion-menu.meta.completion.current": "noinherit bg:default noreverse fg:" + tokens["primary"],
            "scrollbar.background": "noinherit bg:default noreverse",
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
        return merge_styles([style_from_pygments_cls(pyg_cls), base_style])
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
    "interim_text": {"hex": "#A2ABC0", "rich": "bright_black", "pt": "ansibrightblack"},
    "interim_border": {"hex": "#4B5563", "rich": "bright_black", "pt": "ansibrightblack"},
    "diff_stat_add": {"hex": "#50FA7B", "rich": "green", "pt": "ansigreen"},
    "diff_stat_del": {"hex": "#FF5555", "rich": "red", "pt": "ansired"},
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
    "interim_text": "#A2ABC0", # interim capsule text
    "interim_border": "#4B5563", # interim capsule border
    "diff_stat_add": "#50FA7B",  # diff stat additions
    "diff_stat_del": "#FF5555",  # diff stat deletions
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
