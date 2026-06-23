"""Ladda preferences fran ~/.hund/preferences.json."""
from __future__ import annotations
import json
from pathlib import Path
from .model import Preferences, Preference

def load() -> Preferences:
    from ..paths import hund_home
    path = hund_home() / "preferences.json"
    if not path.exists():
        return Preferences()
    try:
        data = json.loads(path.read_text("utf-8"))
        items = [Preference(**item) for item in data.get("items", [])]
        return Preferences(items=items)
    except Exception:
        return Preferences()
