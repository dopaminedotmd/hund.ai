"""Tests for Export Engine — pairs, filters, manifest, store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hund.export.filters import Filter
from hund.export.manifest import ExportManifest
from hund.export.store import log_export, list_exports


# ── Filters ────────────────────────────────────────────────────────


def test_filter_empty_build():
    f = Filter()
    where, params = f.build()
    assert where == ""
    assert params == []


def test_filter_with_session():
    f = Filter().with_session("session-123")
    where, params = f.build()
    assert "session_id" in where
    assert "session-123" in params


def test_filter_with_event_type():
    f = Filter().with_event_type("run_completed")
    where, params = f.build()
    assert "event_type" in where
    assert "run_completed" in params


def test_filter_with_run_and_limit():
    f = Filter().with_run("run-001").with_limit(50)
    where, params = f.build()
    assert "run_id" in where
    assert "run-001" in params


def test_filter_to_dict():
    f = Filter().with_session("s1").with_risk("safe")
    d = f.to_dict()
    assert d["session_id"] == "s1"
    assert d["risk"] == "safe"


def test_filter_chainable():
    f = Filter().with_session("s1").with_event_type("t1").with_actor("agent")
    where, params = f.build()
    assert "session_id" in where
    assert "event_type" in where
    assert "actor" in where
    assert len(params) == 3


# ── Manifest ────────────────────────────────────────────────────────


def test_manifest_creation(tmp_path):
    manifest = ExportManifest(
        export_format="jsonl",
        pair_count=42,
        output_path=str(tmp_path / "export.jsonl"),
    )
    d = manifest.to_dict()
    assert d["export_format"] == "jsonl"
    assert d["pair_count"] == 42
    assert d["redactor_version"] == "v2.0.0"
    assert "export_id" in d
    assert "exported_at" in d


def test_manifest_save_and_load(tmp_path):
    out = tmp_path / "test_export.jsonl"
    manifest = ExportManifest(
        export_format="sft",
        pair_count=10,
        output_path=str(out),
    )
    saved = manifest.save(out)
    assert saved.exists()
    assert saved.suffix == ".json"  # .manifest.json has .json suffix
    assert "manifest" in saved.stem

    loaded = ExportManifest.load(saved)
    assert loaded.export_format == "sft"
    assert loaded.pair_count == 10
    assert loaded.export_id == manifest.export_id


def test_manifest_with_filter(tmp_path):
    f = Filter().with_session("test-session").with_limit(100)
    manifest = ExportManifest(
        export_format="jsonl",
        filter_obj=f,
        pair_count=5,
    )
    d = manifest.to_dict()
    assert d["filters"]["session_id"] == "test-session"
    assert d["filters"]["limit"] == 100


# ── Store ───────────────────────────────────────────────────────────


def test_log_export(tmp_path):
    db = tmp_path / "test.db"
    eid = log_export(
        export_format="jsonl",
        pair_count=10,
        output_path="/tmp/export.jsonl",
        filters_json='{"session": "s1"}',
        redactor_version="v2.0.0",
        db_path=db,
    )
    assert eid is not None
    assert len(eid) > 0


def test_list_exports(tmp_path):
    db = tmp_path / "test.db"
    log_export("jsonl", 10, "/tmp/a.jsonl", db_path=db)
    log_export("sft", 20, "/tmp/b.jsonl", db_path=db)

    exports = list_exports(limit=10, db_path=db)
    assert len(exports) == 2


def test_list_exports_empty(tmp_path):
    db = tmp_path / "test.db"
    exports = list_exports(limit=10, db_path=db)
    assert exports == []


def test_list_exports_ordered(tmp_path):
    db = tmp_path / "test.db"
    import time
    log_export("jsonl", 5, "/tmp/old.jsonl", db_path=db)
    time.sleep(0.01)
    log_export("sft", 15, "/tmp/new.jsonl", db_path=db)

    exports = list_exports(limit=10, db_path=db)
    # Should be ordered by created_at DESC
    assert exports[0]["pair_count"] == 15
    assert exports[1]["pair_count"] == 5


def test_list_exports_limit(tmp_path):
    db = tmp_path / "test.db"
    for i in range(5):
        log_export("jsonl", i, f"/tmp/{i}.jsonl", db_path=db)

    exports = list_exports(limit=3, db_path=db)
    assert len(exports) == 3


# ── Engine ─────────────────────────────────────────────────────────


def test_engine_dry_run_empty():
    from hund.export.engine import ExportEngine, PromptResponsePair

    engine = ExportEngine()
    stats = engine.dry_run([])
    assert stats["pair_count"] == 0
    assert stats["risk_counts"] == {}


def test_engine_dry_run_with_pairs():
    from hund.export.engine import ExportEngine, PromptResponsePair
    from dataclasses import dataclass, field

    pairs = [
        PromptResponsePair(
            pair_id="p1", session_id="s1", run_id="r1",
            prompt="Hello", response="World",
            risk="safe", blocked_fields=[], created_at="2024-01-01",
        ),
        PromptResponsePair(
            pair_id="p2", session_id="s1", run_id="r1",
            prompt="Test", response="Data",
            risk="review_required", blocked_fields=["ip"],
            created_at="2024-01-02",
        ),
    ]

    engine = ExportEngine()
    stats = engine.dry_run(pairs)
    assert stats["pair_count"] == 2
    assert stats["risk_counts"]["safe"] == 1
    assert stats["risk_counts"]["review_required"] == 1
    assert "ip" in stats["blocked_fields"]


def test_engine_export_jsonl(tmp_path):
    from hund.export.engine import ExportEngine, PromptResponsePair

    pairs = [
        PromptResponsePair(
            pair_id="p1", session_id="s1", run_id="r1",
            prompt="Hello", response="World",
            created_at="2024-01-01",
        ),
    ]

    engine = ExportEngine()
    out = tmp_path / "test.jsonl"
    engine.export_to_jsonl(pairs, out)
    assert out.exists()

    lines = out.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["prompt"] == "Hello"
    assert data["response"] == "World"


def test_engine_export_sft(tmp_path):
    from hund.export.engine import ExportEngine, PromptResponsePair

    pairs = [
        PromptResponsePair(
            pair_id="p1", session_id="s1", run_id="r1",
            prompt="Hello", response="World",
            created_at="2024-01-01",
        ),
    ]

    engine = ExportEngine()
    out = tmp_path / "test.jsonl"
    engine.export_to_sft(pairs, out)
    assert out.exists()

    lines = out.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert "messages" in data
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"


def test_engine_save_manifest(tmp_path):
    from hund.export.engine import ExportEngine, PromptResponsePair

    pairs = [
        PromptResponsePair(
            pair_id="p1", session_id="s1", run_id="r1",
            prompt="Hello", response="World",
            created_at="2024-01-01",
        ),
    ]

    engine = ExportEngine()
    out = tmp_path / "test.jsonl"
    manifest = engine.save_manifest(pairs, out, export_format="jsonl")
    assert manifest.pair_count == 1
    assert out.with_suffix(".manifest.json").exists()


def test_engine_export_nonexistent_db(tmp_path):
    """Engine should handle empty DB gracefully."""
    from hund.export.engine import ExportEngine, Filter

    engine = ExportEngine(db_path=tmp_path / "nonexistent.db")
    pairs = engine.build_pairs(Filter().with_limit(10))
    assert pairs == []


def test_engine_query_traces_empty(tmp_path):
    from hund.export.engine import ExportEngine, Filter

    engine = ExportEngine(db_path=tmp_path / "empty.db")
    traces = engine.query_traces(Filter().with_limit(10))
    assert traces == []
