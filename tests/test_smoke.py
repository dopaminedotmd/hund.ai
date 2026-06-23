"""Smoke-test: paket importerar, version finns, CLI svarar."""
from __future__ import annotations

import hund
from hund import __version__


def test_version_exists():
    assert isinstance(__version__, str) and __version__
    assert __version__ == hund.__version__


def test_main_app_constructed():
    from hund.main import app

    assert app.info.name == "hund"


def test_doctor_profiles_environment(tmp_path):
    from hund.doctor import profile_environment

    prof = profile_environment(workspace=tmp_path)
    assert prof.os  # inte tom
    assert "has_git" in prof.capabilities
    assert str(tmp_path) in prof.workspace
