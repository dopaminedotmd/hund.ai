from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from hund.config import HundConfig, ProviderConfig
from hund.providers.catalog import MODEL_OPTIONS, activate_model, credential_for
from hund.secrets import delete_api_key, load_api_key, save_api_key
from hund.stats import velocity
from hund.store.sqlite import connect, connect_requests
from hund.tools.registry import Tool
from hund.ui.screen_render import (
    render_skills,
    render_stats,
    render_tools,
    render_usage,
)
from hund.ui.screen_state import DestinationView, OverlayView, ScreenController
from hund.ui.snapshots import (
    SessionUsage,
    SkillsSnapshot,
    StatsSnapshot,
    ToolsSnapshot,
    UsageSnapshot,
    collect_usage,
)


def _snapshots():
    today = date(2026, 8, 24)
    return (
        StatsSnapshot(
            "test", (), (), (0,) * 7,
            tuple(today - timedelta(days=n) for n in range(6, -1, -1)),
            (), False,
        ),
        SkillsSnapshot((), (), 8),
        ToolsSnapshot((), ()),
        UsageSnapshot((), date(2026, 2, 1), today, None, SessionUsage(None, None, None)),
    )


@pytest.mark.parametrize("width", [120, 80, 60, 42])
@pytest.mark.parametrize("height", [40, 24, 16])
def test_fullscreen_render_matrix_stays_inside_terminal(width, height):
    stats, skills, tools, usage = _snapshots()
    rendered = (
        render_stats(stats, width=width, height=height),
        render_skills(skills, width=width, height=height),
        render_tools(tools, width=width, height=height),
        render_usage(usage, width=width, height=height),
    )
    for screen in rendered:
        assert len(screen.splitlines()) == height
        assert max(map(len, screen.splitlines())) <= width - 1
        assert "Esc" in screen


def test_ascii_fallback_preserves_geometry():
    stats, _, _, _ = _snapshots()
    rendered = render_stats(stats, width=42, height=16, ascii_only=True)
    assert "╔" not in rendered
    assert rendered.splitlines()[0].startswith("+")
    assert all(len(line) == 41 for line in rendered.splitlines())


def test_controller_escape_priority_and_confirmation_guard():
    state = ScreenController(destination=DestinationView.SKILLS, overlay=OverlayView.CONFIRM)
    assert not state.open_destination(DestinationView.TOOLS)
    assert not state.open_overlay(OverlayView.THEME)
    assert state.close_escape() == "confirm"
    state.open_overlay(OverlayView.MODEL_CUSTOM)
    assert state.close_escape() == "nested"
    assert state.overlay is OverlayView.MODEL
    assert state.close_escape() == "overlay"
    state.detail["skills"] = "python"
    assert state.close_escape() == "detail"
    assert state.close_escape() == "destination"
    assert state.destination is DestinationView.CHAT


def test_velocity_compares_distinct_adjacent_windows(monkeypatch):
    calls = []

    def fake(start, end, *, home=None):
        calls.append((start, end))
        value = 80.0 if len(calls) == 1 else 70.0
        return {"precision": {"value": value}}

    monkeypatch.setattr(velocity, "compute_all_since", fake)
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    result = velocity.compute_velocity(now=now)
    assert calls == [
        (now - timedelta(days=7), now),
        (now - timedelta(days=14), now - timedelta(days=7)),
    ]
    assert result["precision"]["delta"] == 10


def test_usage_uses_local_days_and_session_run_links(tmp_path):
    req = connect_requests(tmp_path / "logs" / "requests.db")
    req.executemany(
        "INSERT INTO requests (id, created_at, prompt_tokens, completion_tokens, run_id) VALUES (?,?,?,?,?)",
        [
            ("a", "2026-02-28T23:30:00+00:00", 10, 2, "run-a"),
            ("b", "2026-03-01T10:00:00+00:00", 20, 3, "other"),
        ],
    )
    req.commit()
    req.close()
    core = connect(tmp_path / "hund.db")
    core.execute(
        """INSERT INTO trace_events
        (event_id,schema_version,created_at,session_id,run_id,actor,event_type,
         payload_hash,payload_hash_algorithm,redactor_version)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        ("e", 1, "2026-03-01T00:00:00+00:00", "session-a", "run-a", "agent", "turn", "h", "sha256", "1"),
    )
    core.commit()
    core.close()
    local_now = datetime(2026, 8, 24, 12, tzinfo=timezone(timedelta(hours=1)))
    snapshot = collect_usage(home=tmp_path, session_id="session-a", now=local_now)
    march_first = next(day for day in snapshot.days if day.day == date(2026, 3, 1))
    assert (march_first.prompt_tokens, march_first.output_tokens, march_first.requests) == (30, 5, 2)
    assert snapshot.session == SessionUsage(10, 2, 1)
    assert len(snapshot.days) == (snapshot.last_day - snapshot.first_day).days + 1


def test_usage_does_not_claim_global_tokens_as_session_data(tmp_path):
    req = connect_requests(tmp_path / "logs" / "requests.db")
    req.execute(
        "INSERT INTO requests (id, created_at, prompt_tokens, completion_tokens) VALUES (?,?,?,?)",
        ("a", "2026-08-24T00:00:00+00:00", 99, 9),
    )
    req.commit()
    req.close()
    snapshot = collect_usage(
        home=tmp_path, session_id="legacy", now=datetime(2026, 8, 24, tzinfo=timezone.utc)
    )
    assert not snapshot.session.available


def test_credential_environment_precedes_vault(monkeypatch):
    calls = []
    keyring = SimpleNamespace(
        get_password=lambda service, identity: calls.append((service, identity)) or "vault",
        set_password=lambda *args: None,
        delete_password=lambda *args: None,
    )
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment")
    assert load_api_key("OPENROUTER_API_KEY") == "environment"
    assert not calls
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert load_api_key("OPENROUTER_API_KEY") == "vault"
    assert calls[-1] == ("hund.ai", "openrouter")
    assert save_api_key("secret", "openrouter")
    assert delete_api_key("openrouter")


def test_credential_vault_failure_is_closed(monkeypatch):
    broken = SimpleNamespace(
        get_password=lambda *args: (_ for _ in ()).throw(RuntimeError("no vault")),
        set_password=lambda *args: (_ for _ in ()).throw(RuntimeError("no vault")),
        delete_password=lambda *args: (_ for _ in ()).throw(RuntimeError("no vault")),
    )
    monkeypatch.setitem(sys.modules, "keyring", broken)
    monkeypatch.delenv("HUND_API_KEY", raising=False)
    assert load_api_key("HUND_API_KEY", "deepseek") == ""
    assert not save_api_key("never-written", "deepseek")
    assert not delete_api_key("deepseek")


def test_model_catalog_and_atomic_rollback(monkeypatch):
    option = next(item for item in MODEL_OPTIONS if item.provider_id == "openrouter")
    assert option.model_id == "nvidia/nemotron-3.5-lightning:free"
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("HUND_API_KEY", raising=False)

    class BrokenConfig:
        provider = ProviderConfig()

        def save(self):
            raise OSError("disk unavailable")

    old_client = object()
    rt = SimpleNamespace(client=old_client, key="old-key", cfg=BrokenConfig())
    old_provider = rt.cfg.provider.model_copy(deep=True)
    ok, message = activate_model(rt, option)
    assert not ok and "previous provider" in message
    assert rt.client is old_client and rt.key == "old-key"
    assert rt.cfg.provider == old_provider


def test_legacy_bone_config_migrates_without_secret_serialization(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"theme":"bone","provider":{"model":"deepseek-chat"}}', encoding="utf-8")
    cfg = HundConfig.load(path)
    assert cfg.theme == "marshmallow"
    cfg.save(path)
    text = path.read_text(encoding="utf-8")
    assert "marshmallow" in text
    assert "api_key" not in text.replace("api_key_env", "")


def test_tool_ui_metadata_is_backwards_compatible():
    tool = Tool("demo", "description", {"type": "object"}, "safe")
    assert tool.category is None
    assert tool.dispatch_description is None


def test_provider_specific_environment_has_priority(monkeypatch):
    option = next(item for item in MODEL_OPTIONS if item.provider_id == "openrouter")
    monkeypatch.delenv("HUND_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "specific")
    assert credential_for(option) == "specific"


@pytest.mark.parametrize("width", [120, 80, 60, 42])
def test_compact_model_modal_render(width):
    from hund.ui.screen_render import render_model_modal
    modal = render_model_modal(MODEL_OPTIONS, "deepseek-v4-pro", 0, width)
    lines = modal.splitlines()
    # Must fit within safe width and not overflow
    assert max(len(l) for l in lines) <= width - 1
    # Check that model rows exist and are single-line
    assert any("deepseek-v4-pro" in l for l in lines)
    # Check that redundant verbose fields are not rendered on separate lines
    assert not any(" · local" in l or " · remote" in l for l in lines)
    # Check footer
    assert "[Esc] cancel" in modal


def test_screen_tokens_meta_labels():
    from hund.ui.fullscreen import _semantic_screen_fragments
    sample = "║  OS        Windows 11 Pro ║\n║  HOST      razor          ║\n"
    frags = _semantic_screen_fragments(sample)
    meta_frags = [f for f in frags if f[0] == "class:meta_accent"]
    assert any(f[1] == "OS" for f in meta_frags)
    assert any(f[1] == "HOST" for f in meta_frags)


def test_modal_backdrop_dimming_and_escape_priority():
    from hund.ui.fullscreen import _OutputLexer, _MODAL_ACTIVE
    from prompt_toolkit.document import Document

    doc = Document("Hello world\nAnother line")
    lexer = _OutputLexer()

    # When no modal is active
    _MODAL_ACTIVE[0] = False
    assert not lexer.invalidation_hash()
    line_fn = lexer.lex_document(doc)
    assert line_fn(0) != [("class:backdrop", "Hello world")]

    # When modal is active
    _MODAL_ACTIVE[0] = True
    assert lexer.invalidation_hash()
    dim_fn = lexer.lex_document(doc)
    assert dim_fn(0) == [("class:backdrop", "Hello world")]
    assert dim_fn(1) == [("class:backdrop", "Another line")]

    # Reset
    _MODAL_ACTIVE[0] = False

