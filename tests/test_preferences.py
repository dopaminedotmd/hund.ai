"""Tester for preferences system."""
import json
from pathlib import Path
from unittest.mock import patch
import pytest

from hund.preferences.model import Preferences, Preference
from hund.preferences.loader import load


def test_preferences_modes():
    """Verifiera att preferenserna filtreras korrekt efter mode."""
    items = [
        Preference(key="p1", value="v1", mode="always"),
        Preference(key="p2", value="v2", mode="behavioral"),
        Preference(key="p3", value="v3", mode="contextual"),
    ]
    prefs = Preferences(items=items)
    
    always = prefs.get_always()
    assert len(always) == 1
    assert always[0].key == "p1"
    
    behavioral = prefs.get_behavioral()
    assert len(behavioral) == 2
    assert {p.key for p in behavioral} == {"p1", "p2"}
    
    contextual = prefs.get_contextual()
    assert len(contextual) == 2
    assert {p.key for p in contextual} == {"p1", "p3"}


def test_loader_loads_items(tmp_path):
    """Verifiera att loader läser preferences.json från hund_home."""
    preferences_data = {
        "items": [
            {"key": "editor", "value": "code", "mode": "always"},
            {"key": "theme", "value": "dark", "mode": "behavioral"}
        ]
    }
    
    # Skriv temporär preferences.json
    prefs_file = tmp_path / "preferences.json"
    prefs_file.write_text(json.dumps(preferences_data), encoding="utf-8")
    
    with patch("hund.paths.hund_home", return_value=tmp_path):
        prefs = load()
        assert len(prefs.items) == 2
        assert prefs.items[0].key == "editor"
        assert prefs.items[0].value == "code"
        assert prefs.items[0].mode == "always"
        
        assert prefs.items[1].key == "theme"
        assert prefs.items[1].value == "dark"
        assert prefs.items[1].mode == "behavioral"


def test_loader_missing_file(tmp_path):
    """Om filen saknas ska vi returnera en tom Preferences-instans."""
    with patch("hund.paths.hund_home", return_value=tmp_path):
        prefs = load()
        assert len(prefs.items) == 0
