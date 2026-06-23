"""Domain detection v1 — detector + model + persistence."""
from __future__ import annotations

from pathlib import Path

from hund.domains import detector as ddet
from hund.domains.model import DomainDetection, DomainSignal


def test_manifest_pyproject_yields_python_high(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    det = ddet.detect(tmp_path)
    assert det.primary == "python"
    assert det.primary_confidence == "high"
    assert any(s.source == "manifest" and s.domain == "python" for s in det.signals)


def test_manifest_package_json_yields_javascript(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert ddet.detect(tmp_path).primary == "javascript"


def test_filetype_majority(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.rs").write_text("fn main(){}")
    det = ddet.detect(tmp_path)
    assert det.primary == "rust"
    assert det.primary_confidence in {"medium", "high"}


def test_manual_override_wins(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    det = ddet.detect(tmp_path, manual="go")
    assert det.primary == "go"
    assert det.primary_confidence == "high"


def test_commands_signal(tmp_path):
    det = ddet.detect(tmp_path, commands=["uv run pytest -x"])
    assert "python" in det.candidates


def test_empty_workspace_unknown(tmp_path):
    det = ddet.detect(tmp_path)
    assert det.primary == "unknown"
    assert det.signals == ()


def test_candidates_unique(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "f.py").write_text("")
    (tmp_path / "g.py").write_text("")
    det = ddet.detect(tmp_path)
    # python får visas flera gånger i signals men candidates unika
    assert len(det.candidates) == len(set(det.candidates))


def test_persistence_records_and_lists(tmp_path, monkeypatch):
    # peka db på tmp så vi inte förorenar riktig HundHome
    import hund.paths as paths

    db = tmp_path / "hund.db"
    monkeypatch.setattr(paths, "db_path", lambda: db)
    monkeypatch.setattr("hund.store.sqlite.db_path", lambda: db, raising=False)

    det = DomainDetection(
        (
            DomainSignal("python", "high", "manifest"),
            DomainSignal("rust", "medium", "filetype"),
        )
    )
    ddet.record_detection(det)
    rows = ddet.list_domains()
    domains = {r[0]: r for r in rows}
    assert "python" in domains and "rust" in domains
    assert domains["python"][1] == "primary"
    assert domains["rust"][1] == "active"
    assert ddet.get_primary() == "python"


def test_set_primary_demotes_previous(tmp_path, monkeypatch):
    import hund.paths as paths

    db = tmp_path / "hund.db"
    monkeypatch.setattr(paths, "db_path", lambda: db)
    monkeypatch.setattr("hund.store.sqlite.db_path", lambda: db, raising=False)

    ddet.record_detection(
        DomainDetection((DomainSignal("python", "high", "manifest"),))
    )
    assert ddet.get_primary() == "python"
    ddet.set_primary("rust")
    assert ddet.get_primary() == "rust"
    # python demoted till active
    rows = {r[0]: r for r in ddet.list_domains()}
    assert rows["python"][1] == "active"
