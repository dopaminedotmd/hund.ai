"""Tiers — shared tier logic for base stats and progress bars."""
from __future__ import annotations

from typing import Any

TIERS = ["Novice", "Apprentice", "Adept", "Expert", "Master"]
TIER_COLORS = {
    "Novice": "dim white",
    "Apprentice": "green",
    "Adept": "blue",
    "Expert": "purple",
    "Master": "gold1",
}


def build_stat(name: str, value: float | None, thresholds: list[float], higher_better: bool) -> dict[str, Any]:
    """Build a complete stat entry with tier + progress."""
    if value is None:
        return {"name": name, "value": None, "tier": "\u2014", "tier_idx": 0,
                "progress": 0, "next_tier": None, "display": "n/a"}

    tier_idx = 0
    for i, t in enumerate(thresholds):
        if (higher_better and value < t) or (not higher_better and value > t):
            tier_idx = i
            break
    else:
        tier_idx = 4

    tier_name = TIERS[tier_idx]

    if tier_idx < 4:
        if tier_idx > 0:
            current_threshold = thresholds[tier_idx - 1]
        else:
            current_threshold = 0 if higher_better else thresholds[0] * 2
        next_threshold = thresholds[tier_idx]

        if higher_better:
            progress = (value - current_threshold) / (next_threshold - current_threshold) * 100
        else:
            progress = (current_threshold - value) / (current_threshold - next_threshold) * 100

        progress = max(0, min(100, progress))
    else:
        progress = 100

    return {
        "name": name,
        "value": round(value, 1),
        "tier": tier_name,
        "tier_idx": tier_idx + 1,
        "progress": round(progress),
        "next_tier": TIERS[tier_idx + 1] if tier_idx < 4 else None,
        "color": TIER_COLORS[tier_name],
    }


def render_bar(progress: int, width: int = 16) -> str:
    filled = int(width * progress / 100)
    return "\u2588" * filled + "\u2591" * (width - filled)


def render_stat(stat: dict[str, Any]) -> str:
    if stat["value"] is None:
        return f"  {stat['name']:<14}  \u2014 n/a"
    bar = render_bar(stat["progress"])
    line = f"  {stat['name']:<14}  {bar}  {stat['tier']:<11}"
    if stat["next_tier"]:
        line += f" {stat['progress']}% \u25b8 {stat['next_tier']}"
    else:
        line += f" {stat['progress']}%"
    return line
