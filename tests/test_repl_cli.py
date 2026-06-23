"""CLI startup for OpenTUI."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from hund import __version__
from hund.main import app


class _FakeProcess:
    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.wait_called = False

    def wait(self) -> int:
        self.wait_called = True
        return self.exit_code


def test_no_arguments_starts_opentui(monkeypatch):
    calls = []
    process = _FakeProcess()

    def fake_popen(command, cwd):
        calls.append((command, cwd))
        return process

    monkeypatch.setattr("hund.main.subprocess.Popen", fake_popen)

    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0
    assert calls == [
        (
            ["bun", "run", "start"],
            Path(__file__).resolve().parent.parent / "tui",
        )
    ]
    assert process.wait_called


def test_repl_starts_opentui_explicitly(monkeypatch):
    calls = []
    process = _FakeProcess()

    def fake_popen(command, cwd):
        calls.append((command, cwd))
        return process

    monkeypatch.setattr("hund.main.subprocess.Popen", fake_popen)

    result = CliRunner().invoke(app, ["repl"])

    assert result.exit_code == 0
    assert calls
    assert process.wait_called


def test_version_does_not_start_opentui(monkeypatch):
    def unexpected_popen(*args, **kwargs):
        raise AssertionError("OpenTUI must not start for --version")

    monkeypatch.setattr("hund.main.subprocess.Popen", unexpected_popen)

    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert f"hund {__version__}" in result.output


def test_opentui_exit_code_is_propagated(monkeypatch):
    monkeypatch.setattr(
        "hund.main.subprocess.Popen",
        lambda command, cwd: _FakeProcess(exit_code=7),
    )

    result = CliRunner().invoke(app, ["repl"])

    assert result.exit_code == 7
