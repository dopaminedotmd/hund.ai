"""Tests for Gate A8: run-clean.ps1 launcher script validation."""
from pathlib import Path
import re


def test_run_clean_script_exists_and_has_required_guards():
    repo_root = Path(__file__).parent.parent
    script_path = repo_root / "run-clean.ps1"
    assert script_path.is_file(), "run-clean.ps1 must exist in repo root"

    content = script_path.read_text(encoding="utf-8")

    # Guard 1: checks .venv/Scripts/hund.exe existence
    assert ".venv" in content and "hund.exe" in content

    # Guard 2: sets isolated LOCALAPPDATA with timestamped path
    assert "LOCALAPPDATA" in content
    assert "Get-Date" in content or "timestamp" in content.lower()

    # Guard 3: default does not delete anything
    assert "Remove-Item" not in content or "if ($Force" in content or "if ($Reset" in content

    # Guard 4: prints exact test home path
    assert "Write-Host" in content or "Write-Output" in content
