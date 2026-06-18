"""HundHome — äger Hund lokala fillayout.

Windows:  %LOCALAPPDATA%/hund/
Posix:    ~/.hund/

Layout (växer in):
    hund/
    ├── config.json          # provider/model/flags (API-nyckel LAGRAS EJ här)
    ├── hund.db              # core SQLite: gap_events, proposals, domains
    ├── logs/                # prestandadata (fas 9.5 Del D)
    │   ├── requests.db
    │   └── tool_events.db
    ├── brain/               # deklarativ hjärna (fas 9.5 Del C)
    │   ├── persona.md
    │   ├── policy.json
    │   ├── skills/
    │   └── knowledge/
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
    (home / "logs").mkdir(parents=True, exist_ok=True)
    (home / "brain" / "skills").mkdir(parents=True, exist_ok=True)
    (home / "brain" / "knowledge").mkdir(parents=True, exist_ok=True)
    return home


def db_path() -> Path:
    """Core-DB: gap_events, proposals, knowledge_units(legacy), domains."""
    return hund_home() / "hund.db"


def config_path() -> Path:
    return hund_home() / "config.json"


def logs_dir() -> Path:
    """Prestationsdata (råa metrics) — separerad från core-DB i fas 9.5 Del D."""
    return hund_home() / "logs"


def requests_db_path() -> Path:
    return logs_dir() / "requests.db"


def tool_events_db_path() -> Path:
    return logs_dir() / "tool_events.db"


def brain_dir() -> Path:
    """Deklarativ hjärna — det Hund KAN. Fas 9.5 Del C."""
    return hund_home() / "brain"


def brain_skills_dir() -> Path:
    return brain_dir() / "skills"


def brain_knowledge_dir() -> Path:
    return brain_dir() / "knowledge"


def brain_policy_path() -> Path:
    return brain_dir() / "policy.json"


def brain_persona_path() -> Path:
    return brain_dir() / "persona.md"
