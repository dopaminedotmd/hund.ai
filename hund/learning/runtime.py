"""Runtime adapter between completed agent turns and durable learning."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import threading
from typing import Any

from ..store.sqlite import connect
from ..trace.events import list_events_by_run
from ..domains.xp import list_xp_events
from ..knowledge import db as knowledge_db
from .ledger import append_event, enqueue_job, get_event, get_job
from .redactor import redact_text
from .worker import process_pending_learning_jobs
from .machine_lifecycle import MachineLifecycle
from .destination_router import CompletedTurnObservation
from .skill_need import ShadowSkillNeedEngine
from .skill_proposals import SkillProposalStore


_SKILL_NEED_SHADOW = ShadowSkillNeedEngine()


_RECEIPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_receipts (
    receipt_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_learning_receipts_created
ON learning_receipts(created_at DESC);
"""


@dataclass(frozen=True)
class LearningReceipt:
    kind: str
    headline: str
    status: str
    domain: str = "general"
    knowledge_id: str = ""
    evidence_count: int = 0
    confidence: float = 0.0
    xp_delta: int = 0
    xp_reason: str = ""
    receipt_id: str = ""
    job_id: str = ""
    turn_id: str = ""
    session_id: str = ""
    run_id: str = ""
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    audit_ids: tuple[str, ...] = field(default_factory=tuple)


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:20]}"


def _ensure_receipts(db_path: Path | str | None) -> None:
    conn = connect(Path(db_path) if db_path else None)
    conn.executescript(_RECEIPT_SCHEMA)
    conn.commit()
    conn.close()


def _store_receipt(receipt: LearningReceipt, db_path: Path | str | None) -> None:
    _ensure_receipts(db_path)
    conn = connect(Path(db_path) if db_path else None)
    conn.execute(
        """INSERT OR REPLACE INTO learning_receipts
           (receipt_id, job_id, session_id, turn_id, run_id, created_at, payload)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            receipt.receipt_id,
            receipt.job_id,
            receipt.session_id,
            receipt.turn_id,
            receipt.run_id,
            datetime.now(timezone.utc).isoformat(),
            json.dumps(asdict(receipt), ensure_ascii=False, sort_keys=True),
        ),
    )
    conn.commit()
    conn.close()


def list_receipts(limit: int = 50, db_path: Path | str | None = None) -> list[LearningReceipt]:
    _ensure_receipts(db_path)
    conn = connect(Path(db_path) if db_path else None)
    rows = conn.execute(
        "SELECT payload FROM learning_receipts ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [LearningReceipt(**json.loads(row[0])) for row in rows]


def format_receipt_bundle(receipt: LearningReceipt) -> list[str]:
    """Render one complete receipt bundle in at most three compact lines."""
    if receipt.kind == "no_change":
        return ["  · no durable learning this turn"]
    if receipt.status == "failed":
        return [f"  · learning failed  {receipt.headline}"]
    lines = [f"  · learned   {receipt.headline}"]
    lines.append(
        f"  · evidence  {receipt.evidence_count} signals · {receipt.status} · confidence {receipt.confidence:.2f}"
    )
    if receipt.xp_delta or receipt.xp_reason:
        lines.append(f"  · {receipt.domain:<9} +{receipt.xp_delta} XP · {receipt.xp_reason}")
    return lines[:3]


def receipt_detail_lines(
    receipt: LearningReceipt, db_path: Path | str | None = None
) -> list[str]:
    """Return redacted provenance, queue, knowledge, and XP audit details."""
    lines = [
        f"receipt: {receipt.receipt_id}",
        f"session / turn / run: {receipt.session_id or '-'} / {receipt.turn_id or '-'} / {receipt.run_id or '-'}",
    ]
    if receipt.job_id:
        job = get_job(receipt.job_id, db_path=db_path)
        if job:
            lines.append(
                f"job: {receipt.job_id} · {job['status']} · attempts {job['attempt_count']}"
            )
            if job.get("last_error"):
                lines.append(f"job error: {redact_text(job['last_error']).text}")
    for evidence_id in receipt.evidence_ids:
        event = get_event(evidence_id, db_path=db_path)
        if event is None:
            lines.append(f"evidence: {evidence_id} · unavailable")
            continue
        lines.append(
            f"evidence: {evidence_id} · {event['source_type']} · {event['source_ref']}"
        )
        lines.append(f"  payload: {redact_text(event['payload']).text}")
    if receipt.knowledge_id:
        for audit in knowledge_db.list_audit_trail(receipt.knowledge_id, db_path=db_path):
            lines.append(
                f"audit: {audit.audit_id} · {audit.action} · {audit.old_status or '-'} -> {audit.new_status}"
            )
            lines.append(f"  reason: {redact_text(audit.reason).text}")
    for event in list_xp_events(unit_id=receipt.knowledge_id, db_path=db_path) if receipt.knowledge_id else []:
        lines.append(
            f"XP: {event['event_id']} · +{event['xp_amount']} · {event['event_type']} · {event['xp_algorithm']}"
        )
        lines.append(
            f"  evidence / session / task: {event['evidence_id'] or '-'} / {event['session_id'] or '-'} / {event['task_id'] or '-'}"
        )
    return lines


class RuntimeLearningAdapter:
    """Extract allowed turn evidence and wake the durable worker asynchronously."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        skill_observation_enabled: bool | None = None,
        skill_proposals_enabled: bool | None = None,
        skill_need_engine: Any = None,
    ) -> None:
        self.db_path = db_path
        if skill_observation_enabled is None or skill_proposals_enabled is None:
            from ..config import HundConfig
            cfg = HundConfig.load()
            if skill_observation_enabled is None:
                skill_observation_enabled = cfg.enable_skill_observation
            if skill_proposals_enabled is None:
                skill_proposals_enabled = cfg.enable_skill_proposals
        self.skill_observation_enabled = bool(skill_observation_enabled)
        self.skill_proposals_enabled = bool(skill_proposals_enabled)
        if skill_need_engine is not None:
            self.skill_need_engine = skill_need_engine
        elif self.skill_observation_enabled and self.skill_proposals_enabled:
            self.skill_need_engine = SkillProposalStore(db_path)
        else:
            self.skill_need_engine = _SKILL_NEED_SHADOW

    def _observe_skill_need(
        self, session_id: str, turn_id: str, run_id: str, workspace_id: str, sink: Any
    ) -> None:
        if not self.skill_observation_enabled:
            return
        from ..agent.sessions import messages_for_run

        messages = messages_for_run(session_id, run_id)
        user_text = "\n".join(text for role, text in messages if role == "user")
        assistant_text = "\n".join(text for role, text in messages if role == "assistant")
        if not user_text or not assistant_text:
            return
        clean_user = redact_text(user_text).text
        clean_assistant = redact_text(assistant_text).text
        trace = list_events_by_run(run_id, db_path=Path(self.db_path) if self.db_path else None)
        verified = any(
            event.event_type == "verification_completed"
            and event.payload_redacted.get("passed") is True
            for event in trace
        )
        candidate = self.skill_need_engine.observe(CompletedTurnObservation(
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            workspace_id=workspace_id,
            user_text=clean_user,
            assistant_text=clean_assistant,
            tool_names=tuple(sorted({e.tool_name for e in trace if e.tool_name})),
            verified=verified,
            scope="project" if workspace_id and workspace_id != "global" else "global",
        ))
        if (
            candidate is not None
            and self.skill_proposals_enabled
            and sink is not None
            and hasattr(sink, "skill_seed")
        ):
            sink.skill_seed(candidate)

    def recover(self) -> None:
        """Requeue interrupted jobs and wake a worker after process restart."""
        conn = connect(Path(self.db_path) if self.db_path else None)
        try:
            stale_before = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            conn.execute(
                """UPDATE learning_jobs SET status='pending', claimed_at=NULL
                   WHERE status='running' AND (claimed_at IS NULL OR claimed_at < ?)""",
                (stale_before,),
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
        threading.Thread(target=self._drain, daemon=True).start()

    def enqueue_completed_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        run_id: str,
        workspace_id: str,
        sink: Any = None,
    ) -> str | None:
        try:
            self._observe_skill_need(session_id, turn_id, run_id, workspace_id, sink)
        except Exception:
            pass
        lifecycle = MachineLifecycle(self.db_path)
        lifecycle.record_task_completion("machine", turn_id, session_id)
        lifecycle.record_task_completion(f"workspace:{workspace_id}", turn_id, session_id)
        events = list_events_by_run(run_id, db_path=Path(self.db_path) if self.db_path else None)
        accepted: list[str] = []
        for event in events:
            if event.event_type != "verification_completed":
                continue
            payload_data = event.payload_redacted
            if (
                payload_data.get("passed") is not True
                or not payload_data.get("command")
                or not payload_data.get("evidence_hash")
            ):
                continue
            payload = json.dumps(payload_data, ensure_ascii=False, sort_keys=True)
            clean = redact_text(payload).text
            if not clean.strip():
                continue
            evidence_id = _stable_id("evidence", event.event_id, clean)
            try:
                append_event(
                    session_id=session_id,
                    turn_id=turn_id,
                    event_type="verification_result",
                    source_type="verified_action",
                    source_ref=f"trace:{event.event_id}",
                    workspace_id=workspace_id,
                    candidate_domains=[event.tool_name or "general"],
                    payload=clean,
                    db_path=self.db_path,
                    event_id=evidence_id,
                )
            except Exception:
                if get_event(evidence_id, db_path=self.db_path) is None:
                    continue
            accepted.append(evidence_id)

        if not accepted:
            receipt_id = _stable_id("receipt", run_id, "no_change")
            receipt = LearningReceipt(
                kind="no_change", headline="no durable learning this turn", status="remembered",
                receipt_id=receipt_id, turn_id=turn_id, session_id=session_id, run_id=run_id,
            )
            _store_receipt(receipt, self.db_path)
            return None

        job_id = _stable_id("learnjob", *sorted(accepted))
        enqueue_job(accepted, db_path=self.db_path, job_id=job_id)
        if sink is not None and hasattr(sink, "learning_pending"):
            sink.learning_pending(job_id)
        threading.Thread(
            target=self._drain_and_publish,
            args=(job_id, session_id, turn_id, run_id, sink),
            daemon=True,
        ).start()
        return job_id

    def _drain(self) -> None:
        process_pending_learning_jobs(db_path=self.db_path, max_jobs=25)

    def _drain_and_publish(
        self, job_id: str, session_id: str, turn_id: str, run_id: str, sink: Any
    ) -> None:
        try:
            self._drain()
            job = get_job(job_id, db_path=self.db_path) or {}
            status = "failed" if job.get("status") == "dead" else "remembered"
            evidence_ids = tuple(job.get("event_ids", []))
            matching = [
                unit for unit in knowledge_db.list_units(db_path=self.db_path)
                if set(unit.evidence_ids).intersection(evidence_ids)
            ]
            unit = matching[0] if matching else None
            xp_events = list_xp_events(unit_id=unit.id, db_path=self.db_path) if unit else []
            xp_event = xp_events[-1] if xp_events else None
            headline = (
                "learning job moved to dead letter" if status == "failed"
                else unit.statement if unit else "no durable learning this turn"
            )
            receipt = LearningReceipt(
                kind="validation" if status == "failed" else "knowledge" if unit else "no_change",
                headline=headline,
                status=status if status == "failed" else unit.status if unit else "remembered",
                domain=unit.domain if unit else "general",
                knowledge_id=unit.id if unit else "",
                evidence_count=len(evidence_ids),
                confidence=unit.confidence if unit else 0.0,
                xp_delta=xp_event["xp_amount"] if xp_event else 0,
                xp_reason=xp_event["event_type"] if xp_event else "",
                receipt_id=_stable_id("receipt", job_id),
                job_id=job_id,
                turn_id=turn_id,
                session_id=session_id,
                run_id=run_id,
                evidence_ids=evidence_ids,
                audit_ids=tuple(event["event_id"] for event in xp_events),
            )
        except Exception as exc:
            receipt = LearningReceipt(
                kind="validation", headline=redact_text(str(exc)).text[:120], status="failed",
                receipt_id=_stable_id("receipt", job_id), job_id=job_id,
                turn_id=turn_id, session_id=session_id, run_id=run_id,
            )
        _store_receipt(receipt, self.db_path)
        if sink is not None and hasattr(sink, "learning_receipt"):
            sink.learning_receipt(receipt)
