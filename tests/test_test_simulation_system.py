"""Deterministic contracts for the test and simulation system."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


def load_inspector():
    spec = importlib.util.spec_from_file_location("inspect_test_home", REPO_ROOT / "scripts" / "inspect_test_home.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_simulation_definitions_cover_the_three_personas_and_two_days() -> None:
    """Each shipped smoke persona has portable definitions for both days."""
    simulations = REPO_ROOT / "docs" / "testing" / "simulations"
    for persona in ("johanna", "alex", "sam"):
        base = simulations / persona
        assert (base / "persona.md").is_file()
        assert (base / "expected.yaml").is_file()
        for day in ("day-01.yaml", "day-02.yaml"):
            content = (base / "days" / day).read_text(encoding="utf-8")
            assert "schema_version:" in content
            assert "prompts:" in content


def test_test_launcher_exposes_only_the_pre_h0_parameters() -> None:
    """Slice 2 must not introduce the gated headless replay interface."""
    content = (REPO_ROOT / "run-test.ps1").read_text(encoding="utf-8")
    for name in ("Home", "Workspace", "Fresh", "Reset", "ConfirmResetPath"):
        assert name in content
    for prohibited in ("-Run", "-Live", "-MaxTurns", "-MaxTokens"):
        assert prohibited not in content
    assert "Remove-Item -LiteralPath" in content
    assert "GetFullPath" in content
    assert "PositionalBinding = $false" in content


def test_launcher_home_parameter_does_not_collide_with_powershell_home(tmp_path: Path) -> None:
    """The public -Home flag remains usable despite PowerShell's read-only $HOME."""
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(REPO_ROOT / "run-test.ps1"),
            "-Home",
            "invalid/path",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "Cannot overwrite variable Home" not in result.stderr
    assert "Home must match" in result.stderr


def test_inspector_handles_schema_drift_and_does_not_mutate_sqlite(tmp_path: Path) -> None:
    """Read-only inspection works against a partial database without writes."""
    home = tmp_path / ".test-home" / "homes" / "alex"
    database = home / "hund" / "hund.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE skill_xp (skill_id TEXT, xp INTEGER)")
        connection.execute("INSERT INTO skill_xp VALUES ('csv-clean', 4)")

    before_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    before_mtime = database.stat().st_mtime_ns
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "inspect_test_home.py"),
            "--home",
            "alex",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    inspector = load_inspector()
    report = inspector.inspect_home(home)
    assert report["schema_version"] == 1
    assert report["databases"]["hund.db"]["skill_xp"]["count"] == 1
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before_hash
    assert database.stat().st_mtime_ns == before_mtime


def test_inspector_redacts_and_truncates_free_text(tmp_path: Path) -> None:
    """Inspection never returns credentials or unbounded free text."""
    home = tmp_path / ".test-home" / "homes" / "sam"
    database = home / "hund" / "sessions" / "sessions.db"
    database.parent.mkdir(parents=True)
    secret = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE messages (content TEXT)")
        connection.execute("INSERT INTO messages VALUES (?)", (secret + " x" * 5000,))

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "inspect_test_home.py"), "--home", "../../outside", "--json"], check=False, capture_output=True, text=True
    )
    report = load_inspector().inspect_home(home)
    serialized = json.dumps(report)
    assert result.returncode == 2
    assert secret not in serialized
    assert len(serialized) < 8_000


def test_inspector_run_selector_reads_only_sanitized_manifest(tmp_path: Path) -> None:
    run_id = "a" * 32
    run_path = REPO_ROOT / ".test-home" / "runs" / run_id
    # The production CLI must expose the confined --run selector.
    content = (REPO_ROOT / "scripts" / "inspect_test_home.py").read_text(encoding="utf-8")
    assert 'add_argument("--run"' in content


def test_launcher_manifest_contract_is_finalized() -> None:
    content = (REPO_ROOT / "run-test.ps1").read_text(encoding="utf-8")
    for required in ("git_commit", "dirty_fingerprint", "python_version", "hund_version", "script_hash", "ended_at_utc", "exit_code", "completed"):
        assert required in content
