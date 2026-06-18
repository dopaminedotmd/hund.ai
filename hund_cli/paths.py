"""HundHome — äger Hund lokala fillayout.

Windows:  %LOCALAPPDATA%/hund/
Posix:    ~/.hund/

Layout (växer in):
    hund/
    ├── config.json          # provider/model/flags (API-nyckel LAGRAS EJ här)
    ├── hund.db              # SQLite: sessions, stats, gap events
    ├── experience/          # telemetry/learning lokalt
    └── backups/             # rollback snapshots
"""
from __future__ import annotations

import os
from pathlib import Path


def hund_home() -> Path:
    """Rotkatalog för Hund lokal data. Skapas ej här — endast på begäran."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "hund"
    return Path.home() / ".hund"


def ensure_home() -> Path:
    """Skapa HundHome (och nödvändiga underkataloger) om den saknas."""
    home = hund_home()
    (home / "experience").mkdir(parents=True, exist_ok=True)
    (home / "backups").mkdir(parents=True, exist_ok=True)
    return home


def db_path() -> Path:
    return hund_home() / "hund.db"


def config_path() -> Path:
    return hund_home() / "config.json"
