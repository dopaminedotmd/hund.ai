"""Security specification for command-sensitive terminal classification."""
from __future__ import annotations

import pytest

from hund.agent.safety import PermissionEngine, RiskLevel


@pytest.mark.parametrize(
    "command",
    [
        "dir",
        "ls -la",
        "Get-Location",
        "Get-ChildItem -Force",
        "Test-Path pyproject.toml",
        "rg -n TODO hund",
        "Get-Content pyproject.toml",
        "Select-String -Path pyproject.toml -Pattern pytest",
        "git status --short",
        "git diff -- tests",
        "git log -5",
        "git show HEAD",
        "git branch --list",
        "git rev-parse --show-toplevel",
        "hund --version",
    ],
)
def test_complete_read_only_commands_are_safe(command: str, tmp_path) -> None:
    decision = PermissionEngine(tmp_path).classify(
        "terminal", {"command": command}
    )

    assert decision.risk is RiskLevel.SAFE
    assert decision.allowed is True
    assert decision.policy_id.startswith("terminal.safe.")
    assert decision.session_allowable is False


def test_direct_python_script_run_requires_confirmation(tmp_path) -> None:
    decision = PermissionEngine(tmp_path).classify(
        "terminal", {"command": "python demo.py"}
    )

    assert decision.risk is RiskLevel.CONFIRM


def test_read_only_paths_must_resolve_inside_workspace(tmp_path) -> None:
    inside = tmp_path / "folder with spaces" / "notes.txt"
    inside.parent.mkdir()
    inside.write_text("notes", encoding="utf-8")
    outside = tmp_path.parent / "outside.txt"
    engine = PermissionEngine(tmp_path)

    safe_commands = [
        'Get-Content "folder with spaces\\notes.txt"',
        f'Get-Content "{inside}"',
        'Select-String -Path "folder with spaces\\notes.txt" -Pattern notes',
        "rg -n notes .",
    ]
    confirm_commands = [
        f'Get-Content "{outside}"',
        "Get-Content ..\\outside.txt",
        "Get-Content $env:USERPROFILE\\notes.txt",
        "Get-Content *.txt",
        "Get-Content --unknown notes.txt",
    ]

    assert all(
        engine.classify("terminal", {"command": command}).risk is RiskLevel.SAFE
        for command in safe_commands
    )
    assert all(
        engine.classify("terminal", {"command": command}).risk is RiskLevel.CONFIRM
        for command in confirm_commands
    )


@pytest.mark.parametrize(
    "command",
    [
        "git status; Remove-Item secret.txt",
        "git status && del secret.txt",
        "git status | powershell -Command Remove-Item secret.txt",
        "git status\nRemove-Item secret.txt",
        "echo $(Remove-Item secret.txt)",
        "echo `Remove-Item secret.txt`",
        "powershell -EncodedCommand ZQBjAGgAbwAgAGgAaQA=",
        "cmd /c del secret.txt",
        "python -c \"import os; os.remove('secret.txt')\"",
        "node -e \"require('fs').unlinkSync('secret.txt')\"",
        "custom-script.ps1",
    ],
)
def test_compound_or_arbitrary_execution_is_never_safe(
    command: str, tmp_path
) -> None:
    decision = PermissionEngine(tmp_path).classify(
        "terminal", {"command": command}
    )

    assert decision.risk in {
        RiskLevel.CONFIRM,
        RiskLevel.DANGEROUS,
        RiskLevel.BLOCKED,
    }
    assert decision.allowed is False


def test_git_push_has_stable_session_allowable_policy(tmp_path) -> None:
    decision = PermissionEngine(tmp_path).classify(
        "terminal", {"command": "git push origin main"}
    )

    assert decision.risk is RiskLevel.CONFIRM
    assert decision.policy_id == "terminal.git_push"
    assert decision.session_allowable is True


def test_unknown_terminal_command_can_be_session_allowlisted(tmp_path) -> None:
    decision = PermissionEngine(tmp_path).classify(
        "terminal", {"command": "some-unknown-command --flag"}
    )

    assert decision.risk is RiskLevel.CONFIRM
    assert decision.policy_id == "terminal.unknown"
    assert decision.session_allowable is True


def test_bounded_recursive_delete_is_dangerous_but_root_delete_is_blocked(
    tmp_path,
) -> None:
    engine = PermissionEngine(tmp_path)

    bounded = engine.classify("terminal", {"command": "rm -rf build-cache"})
    root = engine.classify("terminal", {"command": "rm -rf /"})

    assert bounded.risk is RiskLevel.DANGEROUS
    assert bounded.session_allowable is False
    assert root.risk is RiskLevel.BLOCKED


def test_terminal_tool_utf8_output_swedish_characters(tmp_path) -> None:
    """RED/GREEN: terminal tool runs commands with UTF-8 env without cp1252 crash on Swedish characters."""
    import sys
    from hund.tools.terminal_tool import make_handler

    tools = make_handler(tmp_path)
    run_term = tools["terminal"]

    cmd = f'"{sys.executable}" -c "print(\'räksmörgås med citron och majonnäs\')"'
    res = run_term({"command": cmd})
    assert "[exit 0]" in res
    assert "räksmörgås med citron och majonnäs" in res

