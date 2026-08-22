"""Velocity — compare current week to previous week."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base_stats import compute_all


def compute_all_since(start: datetime, end: datetime | None = None) -> dict:
    """Compute stats for a specific time window (future: filter by date)."""
    return compute_all()


def compute_velocity() -> dict:
    """Compare current week's stats to previous week."""
    now = datetime.now(timezone.utc)
    this_week = compute_all_since(now - timedelta(days=7))
    last_week = compute_all_since(now - timedelta(days=14), end=now - timedelta(days=7))

    velocity = {}
    for name in this_week:
        tv = this_week[name].get("value")
        lv = last_week[name].get("value")
        if tv is None or lv is None:
            continue
        delta = tv - lv
        higher_better = name in ("precision", "endurance", "mastery")
        improving = (delta > 0) == higher_better
        velocity[name] = {
            "delta": delta,
            "delta_display": f"{abs(delta):.1f}",
            "improving": improving,
            "current": tv,
            "previous": lv,
        }
    return velocity
