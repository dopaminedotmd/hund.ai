"""Tests for terminal tool cwd parameter and security confinement."""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from hund.tools.terminal_tool import make_handler
from hund.tools.default_tools import register_defaults
from hund.tools import registry


def test_terminal_tool_schema_includes_cwd(tmp_path: Path) -> None:
    register_defaults(tmp_path)
    tool = registry.get("terminal")
    assert tool is not None
    assert "cwd" in tool.parameters["properties"]
    assert "use this instead of cd" in tool.description
    assert tool.base_risk == "confirm"


def test_terminal_tool_runs_in_specified_cwd(tmp_path: Path) -> None:
    sub_dir = tmp_path / ".livetest" / "r2"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "data.txt").write_text("42", encoding="utf-8")

    handlers = make_handler(tmp_path)
    run_terminal = handlers["terminal"]

    res = run_terminal({
        "command": "python -c \"import os; print(open('data.txt').read().strip())\"",
        "cwd": ".livetest/r2",
    })
    assert "[exit 0]" in res
    assert "42" in res


def test_terminal_tool_rejects_path_traversal_escape(tmp_path: Path) -> None:
    handlers = make_handler(tmp_path)
    run_terminal = handlers["terminal"]

    res = run_terminal({
        "command": "echo test",
        "cwd": "../../outside",
    })
    assert "[exit 1]" in res
    assert "is outside workspace root" in res


def test_terminal_tool_rejects_non_existent_cwd(tmp_path: Path) -> None:
    handlers = make_handler(tmp_path)
    run_terminal = handlers["terminal"]

    res = run_terminal({
        "command": "echo test",
        "cwd": "does_not_exist",
    })
    assert "[exit 1]" in res
    assert "does not exist or is not a directory" in res


def test_terminal_tool_defaults_to_workspace_root_without_cwd(tmp_path: Path) -> None:
    (tmp_path / "root_data.txt").write_text("root_value", encoding="utf-8")
    handlers = make_handler(tmp_path)
    run_terminal = handlers["terminal"]

    res = run_terminal({
        "command": "python -c \"import os; print(open('root_data.txt').read().strip())\"",
    })
    assert "[exit 0]" in res
    assert "root_value" in res


def test_terminal_tool_cwd_utf8_encoding_swedish(tmp_path: Path) -> None:
    """RED/GREEN: subprocess environment forces UTF-8 and safely outputs Swedish chars in sub-cwd."""
    import sys

    sub_dir = tmp_path / "svenska_mappen"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "fil.txt").write_text("räksmörgås", encoding="utf-8")

    handlers = make_handler(tmp_path)
    run_terminal = handlers["terminal"]

    res = run_terminal({
        "command": f'"{sys.executable}" -c "import os; print(open(\'fil.txt\', encoding=\'utf-8\').read().strip())"',
        "cwd": "svenska_mappen",
    })
    assert "[exit 0]" in res
    assert "räksmörgås" in res

