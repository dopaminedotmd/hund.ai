"""Read-only, schema-drift-tolerant inspector for isolated Hund test homes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from hund.learning.redactor_v2 import redact_text_v2

SCHEMA_VERSION = 1
MAX_SAMPLE_CHARS = 4000
DATABASES = {
    "hund.db": Path("hund") / "hund.db",
    "sessions.db": Path("hund") / "sessions" / "sessions.db",
    "memory.db": Path("hund") / "memory" / "memory.db",
    "requests.db": Path("hund") / "logs" / "requests.db",
    "tool_events.db": Path("hund") / "logs" / "tool_events.db",
}
INTERESTING_TABLES = ("sessions", "messages", "memory", "skill_xp", "skill_xp_events", "domain_xp", "domain_xp_events", "skill_candidates", "skill_proposals", "proposals", "learning_receipts", "trace_events", "tool_events", "requests")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--home", help="Persona name under .test-home/homes")
    selector.add_argument("--run", help="Run identifier under this repository's .test-home/runs")
    parser.add_argument("--json", action="store_true", help="Emit the versioned JSON schema")
    return parser.parse_args(argv)


def resolved_home(args: argparse.Namespace) -> Path:
    """Return a validated persona base under the test-home boundary."""
    repo_root = Path(__file__).resolve().parent.parent
    homes_root = (repo_root / ".test-home" / "homes").resolve()
    if not args.home or not args.home.isascii() or not args.home.replace("-", "").isalnum() or "/" in args.home or "\\" in args.home:
        raise ValueError("home must match [a-z0-9-]+")
    candidate = (homes_root / args.home).resolve()
    if candidate.parent != homes_root:
        raise ValueError("home must resolve directly under .test-home/homes")
    return candidate


def inspect_run(run_id: str) -> dict[str, Any]:
    """Read a confined run manifest without reading transcript artifacts."""
    if len(run_id) != 32 or any(character not in "0123456789abcdef" for character in run_id):
        raise ValueError("run must be a 32-character lowercase hexadecimal identifier")
    run_path = (Path(__file__).resolve().parent.parent / ".test-home" / "runs" / run_id).resolve()
    runs_root = (Path(__file__).resolve().parent.parent / ".test-home" / "runs").resolve()
    if run_path.parent != runs_root:
        raise ValueError("run must resolve directly under .test-home/runs")
    manifest_path = run_path / "manifest.json"
    if not manifest_path.is_file():
        return {"schema_version": SCHEMA_VERSION, "run_id": run_id, "status": "not available"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "run_id": run_id, "status": "corrupt or unreadable"}
    allowed = ("schema_version", "run_id", "persona", "mode", "live", "started_at_utc", "ended_at_utc", "exit_code", "exit_reason", "completed", "provider", "model")
    return {"schema_version": SCHEMA_VERSION, "run": {key: manifest.get(key) for key in allowed}, "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}


def inspect_database(path: Path) -> dict[str, Any]:
    """Inspect only existing tables through SQLite's immutable read-only URI."""
    if not path.is_file():
        return {"status": "not available"}
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            summary: dict[str, Any] = {"status": "available", "tables": sorted(tables)}
            for table in INTERESTING_TABLES:
                if table not in tables:
                    continue
                count = connection.execute(f' SELECT COUNT(*) FROM "{table}" ').fetchone()[0]
                summary[table] = {"count": count}
                columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
                text_column = next((column for column in ("content", "text", "message", "result", "error") if column in columns), None)
                if text_column and count:
                    value = connection.execute(f' SELECT "{text_column}" FROM "{table}" WHERE "{text_column}" IS NOT NULL LIMIT 1 ').fetchone()[0]
                    if isinstance(value, str):
                        redacted = redact_text_v2(value, max_chars=MAX_SAMPLE_CHARS)
                        summary[table]["sample"] = {
                            "text": None if redacted.risk_level == "blocked" else redacted.text,
                            "risk_level": redacted.risk_level,
                            "blocked_fields": redacted.blocked_fields,
                            "original_length": len(value),
                        }
            return summary
    except sqlite3.Error as exc:
        return {"status": "corrupt or unreadable", "error": type(exc).__name__}


def inspect_home(home: Path) -> dict[str, Any]:
    """Return the stable inspector document without mutating the test home."""
    return {
        "schema_version": SCHEMA_VERSION,
        "home": str(home),
        "databases": {name: inspect_database(home / relative_path) for name, relative_path in DATABASES.items()},
    }


def main(argv: list[str] | None = None) -> int:
    """Run the inspector."""
    try:
        args = parse_args(argv or sys.argv[1:])
        report = inspect_run(args.run) if args.run else inspect_home(resolved_home(args))
    except ValueError as exc:
        print(f"inspection rejected: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True) if args.json else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
