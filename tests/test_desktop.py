"""Tests for the safe Windows desktop shortcut service."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from hund.desktop import SHORTCUT_NAME, create_desktop_shortcut
from hund.font_setup import PROFILE_GUID

_win_only = pytest.mark.skipif(os.name != "nt", reason="Windows desktop shortcut")


def _fake_run(calls):
    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        link = Path(kwargs["env"]["HUND_LNK_PATH"])
        link.parent.mkdir(parents=True, exist_ok=True)
        link.write_bytes(b"fake-lnk")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run


@_win_only
def test_create_desktop_shortcut_passes_values_via_env(tmp_path):
    calls = []
    desktop = tmp_path / "Desktop"
    icon = tmp_path / "Hund" / "hund.ico"
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(b"ico")

    link = create_desktop_shortcut(
        desktop=desktop, icon=icon, working_dir=tmp_path, run=_fake_run(calls),
    )
    assert link == desktop / SHORTCUT_NAME
    assert link.is_file()

    cmd, kwargs = calls[0]
    assert cmd[0] == "powershell"
    assert "-NoProfile" in cmd and "-NonInteractive" in cmd
    assert kwargs.get("shell", False) is False
    assert kwargs.get("check") is True
    env = kwargs["env"]
    assert env["HUND_LNK_PATH"] == str(link)
    assert env["HUND_ICON_PATH"] == str(icon)
    assert env["HUND_LNK_ARGS"] == f"-p {PROFILE_GUID}"
    assert env["HUND_WORK_DIR"] == str(tmp_path)
    # No user value was interpolated into the script source.
    script = cmd[-1]
    assert str(link) not in script
    assert str(icon) not in script


@_win_only
def test_create_desktop_shortcut_verifies_link_created(tmp_path):
    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(OSError):
        create_desktop_shortcut(desktop=tmp_path / "Desktop", run=run)


def test_tool_registered_as_confirm(tmp_path):
    from hund.agent.safety import PermissionEngine
    from hund.tools import registry
    from hund.tools.default_tools import register_defaults

    register_defaults(tmp_path)
    tool = registry.get("create_desktop_shortcut")
    assert tool is not None
    assert tool.base_risk == "confirm"
    # Unknown to _TOOL_BASE_RISK, so PermissionEngine defaults to CONFIRM.
    decision = PermissionEngine(tmp_path).classify("create_desktop_shortcut", {})
    assert decision.risk == "confirm"
