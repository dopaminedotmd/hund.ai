"""Domain-detector — grov, offline, deterministisk.

Signaler: manifest-filer (hög), filändelser (medel), körda kommandon (medel),
cwd-namn (låg), manuell --domain (hög). Ingen nätverksåtkomst, ingen provider.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from ..store.sqlite import connect
from .model import DomainDetection, DomainSignal

# manifest-filnamn -> domain
MANIFEST_RULES: dict[str, str] = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "requirements.txt": "python",
    "Pipfile": "python",
    "package.json": "javascript",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "composer.json": "php",
    "pom.xml": "java",
    "Dockerfile": "devops",
    "docker-compose.yml": "devops",
    ".gitlab-ci.yml": "devops",
    "CMakeLists.txt": "cpp",
}

# filändelse -> domain
EXT_RULES: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".php": "php",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".liquid": "shopify",
    ".ps1": "powershell",
    ".sh": "shell",
}

# kommando-substräng -> domain
COMMAND_RULES: dict[str, str] = {
    "pytest": "python",
    "pip": "python",
    "uv ": "python",
    "npm": "javascript",
    "yarn": "javascript",
    "pnpm": "javascript",
    "cargo": "rust",
    "go test": "go",
    "bundle": "ruby",
    "composer": "php",
    "mvn": "java",
    "docker": "devops",
}

# cwd-nyckelord -> domain (svag)
CWD_RULES: dict[str, str] = {
    "py": "python",
    "node": "javascript",
    "rust": "rust",
    "go-": "go",
    "shop": "shopify",
    "terraform": "devops",
}

_MAX_SCAN_FILES = 500


def _scan_extensions(workspace: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    n = 0
    for root, _dirs, files in os.walk(workspace):
        # hoppa vanliga noice-kataloger
        parts = Path(root).relative_to(workspace).parts
        if any(p in {"node_modules", ".git", "venv", ".venv", "__pycache__", "target", "dist", "build"} for p in parts):
            continue
        for f in files:
            if n >= _MAX_SCAN_FILES:
                return counts
            n += 1
            ext = Path(f).suffix.lower()
            dom = EXT_RULES.get(ext)
            if dom:
                counts[dom] = counts.get(dom, 0) + 1
    return counts


def detect(
    workspace: Path,
    *,
    manual: str | None = None,
    commands: list[str] | None = None,
) -> DomainDetection:
    """Identifiera domän från workspace. Offline, deterministisk."""
    signals: list[DomainSignal] = []

    if manual:
        signals.append(DomainSignal(manual.strip(), "high", "manual"))

    # manifest (rot + en nivå ner)
    for name, dom in MANIFEST_RULES.items():
        if (workspace / name).exists():
            signals.append(DomainSignal(dom, "high", "manifest"))
            break
    for sub in (d for d in workspace.iterdir() if d.is_dir()):
        for name, dom in MANIFEST_RULES.items():
            if (sub / name).exists():
                signals.append(DomainSignal(dom, "medium", "manifest"))

    # filändelser — majoritet ger medium, annars låg
    counts = _scan_extensions(workspace)
    if counts:
        top_dom, top_n = max(counts.items(), key=lambda kv: kv[1])
        total = sum(counts.values())
        conf = "medium" if top_n >= max(2, total * 0.4) else "low"
        signals.append(DomainSignal(top_dom, conf, "filetype"))

    # kommandon
    seen_cmd: set[str] = set()
    for cmd in commands or []:
        low = cmd.lower()
        for needle, dom in COMMAND_RULES.items():
            if needle in low and dom not in seen_cmd:
                seen_cmd.add(dom)
                signals.append(DomainSignal(dom, "medium", "command"))

    # cwd-namn (svagast)
    cwd = workspace.name.lower()
    for needle, dom in CWD_RULES.items():
        if needle in cwd:
            signals.append(DomainSignal(dom, "low", "cwd"))
            break

    return DomainDetection(tuple(signals))


# ---- persistence ----

def record_detection(detection: DomainDetection) -> None:
    """Spara detekterade domäner + markera primary. Idempotent upsert."""
    conn = connect()
    now = datetime.now(timezone.utc).isoformat()
    primary = detection.primary
    for cand in detection.candidates:
        # bästa confidence för denna domän
        best = max(
            (s for s in detection.signals if s.domain == cand),
            key=lambda s: {"low": 0, "medium": 1, "high": 2}.get(s.confidence, 0),
        )
        status = "primary" if cand == primary else "active"
        conn.execute(
            """INSERT INTO domains (domain, status, confidence, detected_at)
               VALUES (?,?,?,?)
               ON CONFLICT(domain) DO UPDATE SET
                 status=excluded.status,
                 confidence=excluded.confidence,
                 detected_at=excluded.detected_at""",
            (cand, status, best.confidence, now),
        )
    conn.commit()
    conn.close()


def list_domains() -> list[tuple]:
    conn = connect()
    rows = conn.execute(
        """SELECT domain, status, confidence, detected_at
           FROM domains ORDER BY status DESC, domain"""
    ).fetchall()
    conn.close()
    return rows


def set_primary(domain: str) -> int:
    """Sätt en domän som primary (demotar tidigare primary till active)."""
    conn = connect()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE domains SET status='active' WHERE status='primary'")
    conn.execute(
        """INSERT INTO domains (domain, status, confidence, detected_at)
           VALUES (?, 'primary', 'high', ?)
           ON CONFLICT(domain) DO UPDATE SET
             status='primary', confidence='high', detected_at=excluded.detected_at""",
        (domain, now),
    )
    conn.commit()
    conn.close()
    return 1


def get_primary() -> str | None:
    conn = connect()
    row = conn.execute(
        "SELECT domain FROM domains WHERE status='primary' LIMIT 1"
    ).fetchone()
    conn.close()
    return row[0] if row else None
