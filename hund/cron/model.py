"""Cron data model — jobs.json i HUND_HOME/cron/."""
from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass
class CronJob:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    schedule: str = ""         # "0 9 * * *" eller "30m" eller "every 2h"
    prompt: str = ""           # uppgift for agenten
    skills: list[str] = field(default_factory=list)
    no_agent: bool = False     # True = script-only, noll tokens
    script: str = ""           # path till script (for no_agent mode)
    enabled: bool = True
    last_run: str | None = None
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "schedule": self.schedule,
            "prompt": self.prompt, "skills": self.skills, "no_agent": self.no_agent,
            "script": self.script, "enabled": self.enabled,
            "last_run": self.last_run, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CronJob":
        return cls(**{k: d.get(k, "") for k in [
            "id","name","schedule","prompt","skills","no_agent","script","enabled","last_run","created_at"
        ]})


def load_jobs(home: Path | None = None) -> list[CronJob]:
    if home is None:
        from ..paths import hund_home
        home = hund_home()
    path = home / "cron" / "jobs.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        return []
    return [CronJob.from_dict(j) for j in data] if isinstance(data, list) else []


def save_jobs(jobs: list[CronJob], home: Path | None = None) -> Path:
    if home is None:
        from ..paths import hund_home
        home = hund_home()
    path = home / "cron" / "jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([j.to_dict() for j in jobs], indent=2, ensure_ascii=False), "utf-8")
    return path
