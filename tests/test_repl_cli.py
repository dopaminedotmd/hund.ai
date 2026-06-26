"""CLI-tester för Hund — verifierar att rätt kommando körs."""
from __future__ import annotations

from typer.testing import CliRunner

from hund import __version__
from hund.main import app


def test_no_arguments_starts_repl(monkeypatch):
    """Utan subkommando: startar REPL (UI förbjudet)."""
    repl_called = []
    def mock_start_opentui():
        raise FileNotFoundError("TUI disabled in tests")
    monkeypatch.setattr("hund.main._start_opentui", mock_start_opentui)
    monkeypatch.setattr("hund.agent.loop.run_repl", lambda: repl_called.append(True) or 0)
    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert repl_called, "REPL startade inte"


def test_repl_starts_repl(monkeypatch):
    """`hund repl` startar REPL."""
    repl_called = []
    monkeypatch.setattr("hund.agent.loop.run_repl", lambda: repl_called.append(True) or 0)
    result = CliRunner().invoke(app, ["repl"])
    assert result.exit_code == 0
    assert repl_called, "REPL startade inte"


def test_version_does_not_start_repl(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("REPL får inte starta för --version")
    monkeypatch.setattr("hund.agent.loop.run_repl", unexpected)
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"hund {__version__}" in result.output
