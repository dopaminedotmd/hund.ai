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
    ├── memory/              # persistent användarminne (fas 9.5 Del A)
    │   ├── user.md
    │   └── environment.md
    ├── sessions/            # sessionsarkiv + FTS5 (fas 9.5 Del B)
    │   └── sessions.db
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
    (home / "memory").mkdir(parents=True, exist_ok=True)
    (home / "sessions").mkdir(parents=True, exist_ok=True)
    (home / "models").mkdir(parents=True, exist_ok=True)
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


def memory_dir() -> Path:
    """Persistent användarminne — ej under brain/. Fas 9.5 Del A."""
    return hund_home() / "memory"


def memory_user_path() -> Path:
    return memory_dir() / "user.md"


def memory_env_path() -> Path:
    return memory_dir() / "environment.md"


def connector_key_path() -> Path:
    """Path to connector HMAC secret key file."""
    return hund_home() / "connector" / "key.json"


def local_models_dir() -> Path:
    """Local GGUF model storage directory."""
    return hund_home() / "models"


def local_model_path() -> Path:
    """Default path to find GGUF models."""
    return local_models_dir()

def local_download_path() -> Path:
    """Path for downloaded GGUF models."""
    p = local_models_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


def sessions_dir() -> Path:
    """Sessionsarkiv + FTS5-index. Fas 9.5 Del B."""
    return hund_home() / "sessions"


def sessions_db_path() -> Path:
    return sessions_dir() / "sessions.db"
