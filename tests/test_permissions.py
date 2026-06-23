"""GATE-TEST: PermissionEngine blockerar i kod, inte bara prompt.

Detta är en av de två gaten (docs/mvp.md komponent 7). Får aldrig bli röd:
  - skriv utanför workspace = BLOCKED
  - självpublicering = BLOCKED
  - okänd tool = minst CONFIRM (inte SAFE)
  - läsning = SAFE auto-tillåtet
"""
from __future__ import annotations

from pathlib import Path

from hund.agent.safety import PermissionEngine, RiskLevel


def test_read_is_safe(tmp_path):
    eng = PermissionEngine(workspace_root=tmp_path)
    d = eng.classify("read_file", {"path": "foo.txt"})
    assert d.risk is RiskLevel.SAFE
    assert d.allowed is True


def test_write_outside_workspace_blocked(tmp_path):
    eng = PermissionEngine(workspace_root=tmp_path)
    # försök skriva utanför workspace via path-traversal
    d = eng.classify("write_file", {"path": "../../etc/passwd"})
    assert d.risk is RiskLevel.BLOCKED
    assert d.allowed is False
    assert "workspace" in d.reason.lower()


def test_write_inside_workspace_is_write(tmp_path):
    eng = PermissionEngine(workspace_root=tmp_path)
    d = eng.classify("write_file", {"path": "notes.txt"})
    assert d.risk is RiskLevel.WRITE
    assert d.allowed is False  # kräver confirm, ej auto


def test_self_publish_always_blocked(tmp_path):
    eng = PermissionEngine(workspace_root=tmp_path)
    for tool in ("self_update", "apply_update", "modify_tcb"):
        d = eng.classify(tool, {})
        assert d.risk is RiskLevel.BLOCKED, tool
        assert d.allowed is False


def test_write_to_tcb_file_blocked(tmp_path):
    eng = PermissionEngine(workspace_root=tmp_path)
    d = eng.classify("write_file", {"path": "hund/agent/safety.py"})
    assert d.risk is RiskLevel.BLOCKED
    assert d.allowed is False
    assert "tcb" in d.reason.lower()


def test_write_to_tcb_dir_blocked(tmp_path):
    eng = PermissionEngine(workspace_root=tmp_path)
    d = eng.classify("write_file", {"path": "hund/updater/apply.py"})
    assert d.risk is RiskLevel.BLOCKED
    assert d.allowed is False
    assert "tcb" in d.reason.lower()


def test_unknown_tool_is_confirm(tmp_path):
    eng = PermissionEngine(workspace_root=tmp_path)
    d = eng.classify("mystery_tool", {})
    assert d.risk in {RiskLevel.CONFIRM, RiskLevel.BLOCKED}
    assert d.risk is not RiskLevel.SAFE  # aldrig auto för okänt
