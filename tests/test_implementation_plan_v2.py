"""Acceptance tests for IMPLEMENTATION_PLAN_V2."""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

from prompt_toolkit.document import Document
from rich.console import Console

from hund.agent.safety import PermissionEngine
from hund.agent.tool_dispatch import dispatch_tool_call
from hund.agent.types import ConfirmResponse, ConfirmVerdict
from hund.agent.user_context import expand_user_context
from hund.learning.runtime import LearningReceipt, format_receipt_bundle
from hund.learning.runtime import RuntimeLearningAdapter, list_receipts
from hund.learning.ledger import get_job, list_events
from hund.learning.research import research_gap
from hund.trace.events import record_event
from hund.store.sqlite import connect
from hund.domains.xp import get_xp, list_xp_events
from hund.knowledge import db as knowledge_db
from hund.tools.default_tools import register_defaults
from hund.ui.confirmation import confirmation_options, edited_argument_copy
from hund.ui.input import SlashCommandCompleter
from hund.ui.mascot import MascotMachine, MascotState
from hund.ui.render import render_response_box, wrap_content


def _console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=100)


def _call(name: str, arguments: str) -> dict:
    return {"function": {"name": name, "arguments": arguments}}


def test_response_rendering_preserves_multiple_blank_lines_and_metadata() -> None:
    fence = chr(96) * 3
    text = f"paragraph\n\n\n- bullet\n\n{fence}python\nprint('x')\n{fence}\n"
    assert wrap_content(text, 120) == text.split("\n")
    narrow = render_response_box(text, 32, meta="1.2s")
    wide = render_response_box(text, 100, meta="1.2s")
    assert narrow.count("│                              │") >= 2
    assert wide.count("│                                                                                                  │") >= 2
    assert "1.2s" in narrow and "1.2s" in wide


def test_confirmation_policy_matrix_and_immutable_edit() -> None:
    expected = {
        "terminal": ["approve_once", "edit", "allow_session", "deny"],
        "write_file": ["approve_once", "edit", "deny"],
        "delete_file": ["approve_once", "deny"],
        "execute_code": ["approve_once", "edit", "deny"],
        "delegate_task": ["approve_once", "edit", "deny"],
        "cronjob": ["approve_once", "edit", "deny"],
        "unknown": ["approve_once", "deny"],
    }
    for tool, verdicts in expected.items():
        assert [verdict.value for verdict, _label in confirmation_options(tool)] == verdicts

    original = {"path": "a.txt", "content": "old", "ignored": 1}
    edited = edited_argument_copy(
        "write_file", original, {"path": "b.txt", "content": "new", "ignored": 2}
    )
    assert original == {"path": "a.txt", "content": "old", "ignored": 1}
    assert edited == {"path": "b.txt", "content": "new", "ignored": 1}


def test_edited_blocked_arguments_are_never_executed(tmp_path: Path) -> None:
    register_defaults(tmp_path)

    class Hooks:
        def __init__(self) -> None:
            self.confirmations = 0
            self.started = 0
            self.blocked_count = 0

        def confirm(self, request):
            self.confirmations += 1
            return ConfirmResponse(
                ConfirmVerdict.EDIT,
                {"path": "../escape.txt", "content": "must not run"},
            )

        def tool_start(self, name, args):
            self.started += 1

        def tool_result(self, name, shown):
            pass

        def blocked(self, name, reason):
            self.blocked_count += 1

        def declined(self, name, reason):
            pass

    hooks = Hooks()
    outcome = dispatch_tool_call(
        _call("write_file", '{"path":"ok.txt","content":"safe"}'),
        PermissionEngine(tmp_path),
        _console(),
        hooks=hooks,
        session_id="edit-reclass",
        run_id="edit-reclass",
    )
    assert outcome.startswith("[blocked]")
    assert hooks.confirmations == 1
    assert hooks.started == 0
    assert hooks.blocked_count == 1
    assert not (tmp_path.parent / "escape.txt").exists()


def test_context_expansion_is_untrusted_and_cannot_escape(tmp_path: Path) -> None:
    (tmp_path / "inside.txt").write_text("safe context", encoding="utf-8")
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("must not leak", encoding="utf-8")
    expanded = expand_user_context(
        "review @file:inside.txt and @file:../outside-secret.txt", tmp_path
    )
    assert "safe context" in expanded.prompt
    assert "untrusted repository context" in expanded.prompt
    assert "must not leak" not in expanded.prompt
    assert "escapes workspace" in expanded.prompt


def test_fuzzy_multiword_and_at_file_completion(tmp_path: Path) -> None:
    (tmp_path / "auth_service.py").write_text("", encoding="utf-8")
    completer = SlashCommandCompleter(tmp_path)
    commands = [
        item.text for item in completer.get_completions(Document("/sk manage"), None)
    ]
    assert "/skills" in commands
    files = [
        item.text for item in completer.get_completions(Document("@file:auth"), None)
    ]
    assert "@file:auth_service.py" in files


def test_learning_receipt_bundle_is_atomic_and_bounded() -> None:
    receipt = LearningReceipt(
        kind="knowledge",
        headline="tests must identify their command",
        status="candidate",
        domain="python",
        knowledge_id="know_1",
        evidence_count=2,
        confidence=0.74,
        xp_delta=1,
        xp_reason="discovery",
    )
    lines = format_receipt_bundle(receipt)
    assert len(lines) == 3
    assert "learned" in lines[0]
    assert "evidence" in lines[1]
    assert "+1 XP" in lines[2]
    assert format_receipt_bundle(
        LearningReceipt(kind="no_change", headline="", status="remembered")
    ) == ["  · no durable learning this turn"]


def test_mascot_state_machine_has_real_run_cycle_and_override() -> None:
    machine = MascotMachine()
    assert machine.state is MascotState.SITTING
    machine.start_turn()
    first = machine.frame(now=machine.entered_at)[1]
    second = machine.frame(now=machine.entered_at + 0.13)[1]
    assert first != second
    machine.finish_turn()
    assert machine.state is MascotState.PLAYFUL
    machine.start_turn()
    assert machine.state is MascotState.RUNNING
    assert "PIL" not in Path("hund/ui/mascot.py").read_text(encoding="utf-8")


def test_runtime_learning_pipeline_is_idempotent_and_audited(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "home"))
    database = tmp_path / "runtime.sqlite"
    record_event(
        db_path=database,
        workspace_id=str(tmp_path),
        session_id="session",
        run_id="run",
        actor="hund",
        event_type="verification_completed",
        policy_version="1.0.0",
        tool_name="terminal",
        payload_unredacted={
            "verification_kind": "test",
            "command": "pytest tests/test_example.py",
            "exit_code": 0,
            "passed": True,
            "stdout_redacted_summary": "3 passed",
            "evidence_hash": "a" * 64,
        },
    )

    class Sink:
        def __init__(self) -> None:
            self.pending = []
            self.receipts = []

        def learning_pending(self, job_id):
            self.pending.append(job_id)

        def learning_receipt(self, receipt):
            self.receipts.append(receipt)

    sink = Sink()
    adapter = RuntimeLearningAdapter(database)
    job_id = adapter.enqueue_completed_turn(
        session_id="session",
        turn_id="turn",
        run_id="run",
        workspace_id=str(tmp_path),
        sink=sink,
    )
    assert job_id
    deadline = time.time() + 5
    while time.time() < deadline and (get_job(job_id, database) or {}).get("status") != "completed":
        time.sleep(0.02)
    assert get_job(job_id, database)["status"] == "completed"
    deadline = time.time() + 2
    while time.time() < deadline and not sink.receipts:
        time.sleep(0.02)
    assert sink.pending == [job_id]
    assert sink.receipts and sink.receipts[-1].status == "candidate"

    adapter.enqueue_completed_turn(
        session_id="session",
        turn_id="turn",
        run_id="run",
        workspace_id=str(tmp_path),
    )
    time.sleep(0.2)
    units = knowledge_db.list_units(db_path=database)
    assert len(units) == 1
    events = list_xp_events(unit_id=units[0].id, db_path=database)
    assert len(events) == 1
    assert events[0]["evidence_id"]
    assert get_xp(units[0].domain, database)["xp"] == 1
    assert list_receipts(db_path=database)


def test_gap_research_requires_verification_two_sources_and_redacts(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "home"))
    database = tmp_path / "research.sqlite"
    conn = connect(database)
    conn.execute(
        """INSERT INTO gap_events(id, created_at, domain, symptom, study_target, status)
           VALUES ('gap-1', 'now', 'python', 'missing fact', '', 'open')"""
    )
    conn.commit()
    conn.close()

    def fake_search(args):
        query = args["query"]
        return (
            f"Result for {query}\nhttps://docs.python.org/example\n"
            "Second source\nhttps://peps.python.org/example\n"
            "token=secret-value-that-must-be-redacted"
        )

    blocked = research_gap(
        "gap-1", ["one"], verified_gap=False, search=fake_search, db_path=database
    )
    assert blocked.status == "unverified_gap"
    queued = research_gap(
        "gap-1",
        ["one", "two", "three"],
        verified_gap=True,
        domain="python",
        search=fake_search,
        db_path=database,
    )
    assert queued.status == "queued"
    assert queued.searches == 2
    evidence = next(item for item in list_events(db_path=database) if item["event_id"] == queued.evidence_id)
    assert "secret-value" not in evidence["payload"]
    assert "[REDACTED:secret]" in evidence["payload"]
