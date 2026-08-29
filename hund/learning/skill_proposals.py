"""Durable, consent-first state for inferred skill proposals."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

from ..store.sqlite import connect
from .destination_router import CompletedTurnObservation
from .skill_need import candidate_from_observation


SCHEMA_VERSION = 1
QUIET_DAYS = 3
DECLINE_DAYS = 21
DECAY_DAYS = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_candidates (
    candidate_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    intent TEXT NOT NULL,
    display_name TEXT NOT NULL,
    scope TEXT NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT '',
    evidence_run_ids TEXT NOT NULL,
    evidence_session_ids TEXT NOT NULL,
    steps TEXT NOT NULL,
    tool_names TEXT NOT NULL,
    state TEXT NOT NULL,
    first_evidence_at TEXT NOT NULL,
    last_evidence_at TEXT NOT NULL,
    suppression_until TEXT,
    changed_summary TEXT NOT NULL DEFAULT '',
    research_after_accept INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS skill_proposals (
    proposal_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    candidate_id TEXT NOT NULL REFERENCES skill_candidates(candidate_id),
    session_id TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_proposals_session
ON skill_proposals(session_id);
CREATE INDEX IF NOT EXISTS idx_skill_proposals_created
ON skill_proposals(created_at DESC);
CREATE TABLE IF NOT EXISTS skill_candidate_quarantine (
    candidate_id TEXT PRIMARY KEY,
    quarantined_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class ProposalState(str, Enum):
    OBSERVING = "observing"
    ELIGIBLE = "eligible"
    QUEUED = "queued"
    PROPOSED = "proposed"
    EDITING = "editing"
    ACCEPTED = "accepted"
    DEFERRED = "deferred"
    DECLINED = "declined"
    NEVER_SUGGEST = "never_suggest"


@dataclass(frozen=True)
class SkillSeed:
    proposal_id: str
    candidate_id: str
    display_name: str
    outcome: str
    evidence_summary: str
    improvement: str
    scope: str
    state: str = ProposalState.PROPOSED.value
    changed_summary: str = ""
    research_after_accept: bool = True
    starts_at_xp: int = 0


@dataclass(frozen=True)
class CandidateSummary:
    candidate_id: str
    display_name: str
    scope: str
    state: str


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _display_name(intent: str) -> str:
    words = re.findall(r"[a-zA-Z0-9åäöÅÄÖ]+", intent)
    return (" ".join(words[:7]).strip() or "Reusable Workflow").title()


def _proposal_id(candidate_id: str, session_id: str, created_at: str) -> str:
    raw = "\x1f".join((candidate_id, session_id, created_at)).encode("utf-8")
    return "skillprop_" + hashlib.sha256(raw).hexdigest()[:20]


def natural_proposal_action(text: str) -> str | None:
    clean = " ".join(text.casefold().split())
    if clean in {"accept", "approve", "godkänn", "acceptera"}:
        return "accept"
    if clean in {"decline", "avböj", "nej tack"}:
        return "decline"
    if clean in {"not now", "later", "inte nu", "senare"}:
        return "later"
    if clean in {"never suggest this", "föreslå aldrig detta"}:
        return "never"
    if clean.startswith(("make it global", "gör den global", "call it ", "kalla den ")):
        return "edit"
    return None


class SkillProposalStore:
    """One SQLite authority for candidate evidence, pacing and consent state."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        quiet_days: int = QUIET_DAYS,
        decline_days: int = DECLINE_DAYS,
        decay_days: int = DECAY_DAYS,
    ) -> None:
        self.db_path = Path(db_path) if db_path else None
        self.quiet_days = max(0, quiet_days)
        self.decline_days = max(1, decline_days)
        self.decay_days = max(1, decay_days)
        conn = self._connect()
        conn.close()

    def _connect(self):
        conn = connect(self.db_path)
        conn.row_factory = __import__("sqlite3").Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        conn.commit()
        return conn

    @staticmethod
    def _json_list(value: str) -> list[str]:
        parsed = json.loads(value)
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError("expected JSON string list")
        return parsed

    def _quarantine(self, conn, row, reason: str, now: datetime) -> None:
        payload = json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
        conn.execute(
            """INSERT OR REPLACE INTO skill_candidate_quarantine
               (candidate_id, quarantined_at, reason, payload) VALUES (?, ?, ?, ?)""",
            (row["candidate_id"], _stamp(now), reason[:160], payload),
        )
        conn.execute(
            "DELETE FROM skill_proposals WHERE candidate_id=?", (row["candidate_id"],)
        )
        conn.execute(
            "DELETE FROM skill_candidates WHERE candidate_id=?", (row["candidate_id"],)
        )

    def observe(
        self, observation: CompletedTurnObservation, *, now: datetime | None = None
    ) -> SkillSeed | None:
        qualified = candidate_from_observation(observation)
        if qualified is None:
            return None
        current = _now(now)
        stamp = _stamp(current)
        conn = self._connect()
        try:
            with conn:
                row = conn.execute(
                    "SELECT * FROM skill_candidates WHERE candidate_id=?",
                    (qualified.candidate_id,),
                ).fetchone()
                runs = set(qualified.evidence_run_ids)
                sessions = {observation.session_id}
                steps = set(qualified.steps)
                tools = set(qualified.tool_names)
                state = ProposalState.OBSERVING.value
                first = stamp
                suppression_until = None
                changed_summary = ""
                display_name = _display_name(qualified.intent)
                scope = qualified.scope
                workspace_id = qualified.workspace_id
                research_after_accept = 1
                if row is not None:
                    try:
                        runs.update(self._json_list(row["evidence_run_ids"]))
                        sessions.update(self._json_list(row["evidence_session_ids"]))
                        steps.update(self._json_list(row["steps"]))
                        tools.update(self._json_list(row["tool_names"]))
                    except Exception as exc:
                        self._quarantine(conn, row, str(exc), current)
                        row = None
                    if row is not None:
                        last = _parse(row["last_evidence_at"])
                        if (
                            last
                            and current - last > timedelta(days=self.decay_days)
                            and row["state"] in {
                                ProposalState.OBSERVING.value,
                                ProposalState.ELIGIBLE.value,
                                ProposalState.QUEUED.value,
                            }
                        ):
                            runs = set(qualified.evidence_run_ids)
                            sessions = {observation.session_id}
                            steps = set(qualified.steps)
                            tools = set(qualified.tool_names)
                            first = stamp
                        else:
                            first = row["first_evidence_at"]
                        state = row["state"]
                        suppression_until = row["suppression_until"]
                        changed_summary = row["changed_summary"]
                        display_name = row["display_name"]
                        scope = row["scope"]
                        workspace_id = row["workspace_id"]
                        research_after_accept = row["research_after_accept"]

                if state == ProposalState.NEVER_SUGGEST.value:
                    next_state = state
                elif state in {
                    ProposalState.PROPOSED.value,
                    ProposalState.EDITING.value,
                    ProposalState.ACCEPTED.value,
                }:
                    next_state = state
                elif suppression_until and (_parse(suppression_until) or current) > current:
                    next_state = state
                else:
                    next_state = (
                        ProposalState.ELIGIBLE.value
                        if len(runs) >= 2 and len(sessions) >= 2
                        else ProposalState.OBSERVING.value
                    )

                values = (
                    qualified.candidate_id, SCHEMA_VERSION, qualified.intent,
                    display_name, scope, workspace_id,
                    json.dumps(sorted(runs)), json.dumps(sorted(sessions)),
                    json.dumps(sorted(steps), ensure_ascii=False),
                    json.dumps(sorted(tools)), next_state, first, stamp,
                    suppression_until, changed_summary, research_after_accept,
                )
                conn.execute(
                    """INSERT OR REPLACE INTO skill_candidates
                       (candidate_id, schema_version, intent, display_name, scope,
                        workspace_id, evidence_run_ids, evidence_session_ids, steps,
                        tool_names, state, first_evidence_at, last_evidence_at,
                        suppression_until, changed_summary, research_after_accept)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
                if next_state != ProposalState.ELIGIBLE.value:
                    return None

                already_session = conn.execute(
                    "SELECT 1 FROM skill_proposals WHERE session_id=? LIMIT 1",
                    (observation.session_id,),
                ).fetchone()
                last_proposal = conn.execute(
                    "SELECT created_at FROM skill_proposals ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                quiet = (
                    last_proposal is not None
                    and current - (_parse(last_proposal["created_at"]) or current)
                    < timedelta(days=self.quiet_days)
                )
                if already_session or quiet:
                    conn.execute(
                        "UPDATE skill_candidates SET state=? WHERE candidate_id=?",
                        (ProposalState.QUEUED.value, qualified.candidate_id),
                    )
                    return None

                proposal_id = _proposal_id(
                    qualified.candidate_id, observation.session_id, stamp
                )
                conn.execute(
                    """INSERT INTO skill_proposals
                       (proposal_id, schema_version, candidate_id, session_id,
                        state, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        proposal_id, SCHEMA_VERSION, qualified.candidate_id,
                        observation.session_id, ProposalState.PROPOSED.value,
                        stamp, stamp,
                    ),
                )
                conn.execute(
                    "UPDATE skill_candidates SET state=? WHERE candidate_id=?",
                    (ProposalState.PROPOSED.value, qualified.candidate_id),
                )
                return SkillSeed(
                    proposal_id=proposal_id,
                    candidate_id=qualified.candidate_id,
                    display_name=display_name,
                    outcome=qualified.intent,
                    evidence_summary=(
                        f"Observed across {len(runs)} related tasks in "
                        f"{len(sessions)} sessions."
                    ),
                    improvement="Make this workflow consistent and easier to verify.",
                    scope=scope,
                    changed_summary=changed_summary,
                    research_after_accept=bool(research_after_accept),
                )
        finally:
            conn.close()

    def get_proposal(self, proposal_id: str) -> SkillSeed | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT p.proposal_id, p.state proposal_state, c.*
                   FROM skill_proposals p JOIN skill_candidates c
                   ON c.candidate_id=p.candidate_id WHERE p.proposal_id=?""",
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None
            try:
                runs = self._json_list(row["evidence_run_ids"])
                sessions = self._json_list(row["evidence_session_ids"])
            except Exception as exc:
                with conn:
                    self._quarantine(conn, row, str(exc), _now())
                return None
            return SkillSeed(
                proposal_id=row["proposal_id"],
                candidate_id=row["candidate_id"],
                display_name=row["display_name"],
                outcome=row["intent"],
                evidence_summary=(
                    f"Observed across {len(runs)} related tasks in {len(sessions)} sessions."
                ),
                improvement="Make this workflow consistent and easier to verify.",
                scope=row["scope"],
                state=row["proposal_state"],
                changed_summary=row["changed_summary"],
                research_after_accept=bool(row["research_after_accept"]),
            )
        finally:
            conn.close()

    def respond(
        self,
        proposal_id: str,
        action: str,
        *,
        edit_text: str = "",
        now: datetime | None = None,
    ) -> SkillSeed | None:
        current = _now(now)
        conn = self._connect()
        try:
            with conn:
                row = conn.execute(
                    """SELECT p.*, c.display_name, c.scope, c.intent
                       FROM skill_proposals p JOIN skill_candidates c
                       ON c.candidate_id=p.candidate_id WHERE p.proposal_id=?""",
                    (proposal_id,),
                ).fetchone()
                if row is None:
                    return None
                target = {
                    "accept": ProposalState.ACCEPTED,
                    "edit": ProposalState.EDITING,
                    "decline": ProposalState.DECLINED,
                    "later": ProposalState.DEFERRED,
                    "never": ProposalState.NEVER_SUGGEST,
                }.get(action)
                if action == "apply_edit":
                    target = ProposalState.PROPOSED
                if target is None:
                    raise ValueError(f"unknown proposal action: {action}")
                if row["state"] not in {
                    ProposalState.PROPOSED.value,
                    ProposalState.EDITING.value,
                }:
                    return self.get_proposal(proposal_id)

                candidate_updates = {
                    "state": target.value,
                    "suppression_until": None,
                    "display_name": row["display_name"],
                    "scope": row["scope"],
                    "changed_summary": "",
                    "research_after_accept": 1,
                }
                if target is ProposalState.DECLINED:
                    candidate_updates["suppression_until"] = _stamp(
                        current + timedelta(days=self.decline_days)
                    )
                elif target is ProposalState.DEFERRED:
                    candidate_updates["suppression_until"] = _stamp(
                        current + timedelta(days=self.quiet_days)
                    )
                elif target is ProposalState.NEVER_SUGGEST:
                    candidate_updates["suppression_until"] = "9999-12-31T23:59:59+00:00"
                elif action == "apply_edit":
                    clean = " ".join(edit_text.split())[:240]
                    name_match = re.search(
                        r"(?:call it|kalla den)\s+([^.!?]+)", clean, re.I
                    )
                    changes: list[str] = []
                    if name_match:
                        candidate_updates["display_name"] = name_match.group(1)[:80]
                        changes.append("name")
                    if re.search(r"\b(?:global|globalt|global)\b", clean, re.I):
                        candidate_updates["scope"] = "global"
                        changes.append("scope")
                    elif re.search(r"\b(?:project|projekt)\b", clean, re.I):
                        candidate_updates["scope"] = "project"
                        changes.append("scope")
                    if re.search(r"(?:don't|do not|utan|ingen)\s+(?:web[- ]?search|research|webbsök)", clean, re.I):
                        candidate_updates["research_after_accept"] = 0
                        changes.append("research")
                    candidate_updates["changed_summary"] = (
                        ", ".join(dict.fromkeys(changes)) or "workflow"
                    )

                conn.execute(
                    """UPDATE skill_candidates SET state=?, suppression_until=?,
                       display_name=?, scope=?, changed_summary=?,
                       research_after_accept=? WHERE candidate_id=?""",
                    (
                        candidate_updates["state"],
                        candidate_updates["suppression_until"],
                        candidate_updates["display_name"],
                        candidate_updates["scope"],
                        candidate_updates["changed_summary"],
                        candidate_updates["research_after_accept"],
                        row["candidate_id"],
                    ),
                )
                conn.execute(
                    "UPDATE skill_proposals SET state=?, updated_at=? WHERE proposal_id=?",
                    (target.value, _stamp(current), proposal_id),
                )
        finally:
            conn.close()
        return self.get_proposal(proposal_id)

    def list_candidates(
        self, states: Iterable[str] | None = None
    ) -> tuple[CandidateSummary, ...]:
        wanted = set(states or ())
        conn = self._connect()
        items: list[CandidateSummary] = []
        try:
            rows = conn.execute(
                "SELECT * FROM skill_candidates ORDER BY last_evidence_at DESC"
            ).fetchall()
            for row in rows:
                try:
                    self._json_list(row["evidence_run_ids"])
                    self._json_list(row["evidence_session_ids"])
                    self._json_list(row["steps"])
                    self._json_list(row["tool_names"])
                except Exception as exc:
                    with conn:
                        self._quarantine(conn, row, str(exc), _now())
                    continue
                if not wanted or row["state"] in wanted:
                    items.append(
                        CandidateSummary(
                            row["candidate_id"], row["display_name"],
                            row["scope"], row["state"],
                        )
                    )
        finally:
            conn.close()
        return tuple(items)

    def unsuppress(self, candidate_id: str) -> bool:
        conn = self._connect()
        try:
            with conn:
                cursor = conn.execute(
                    """UPDATE skill_candidates
                       SET state=?, suppression_until=NULL, changed_summary=''
                       WHERE candidate_id=? AND state IN (?, ?, ?)""",
                    (
                        ProposalState.ELIGIBLE.value, candidate_id,
                        ProposalState.DEFERRED.value,
                        ProposalState.DECLINED.value,
                        ProposalState.NEVER_SUGGEST.value,
                    ),
                )
            return cursor.rowcount == 1
        finally:
            conn.close()


def materialize_accepted_proposal(
    proposal_id: str,
    *,
    db_path: Path | str | None = None,
    home: Path | None = None,
    workspace_path: Path | None = None,
    desired_disposition: str = "vault",
) -> tuple[bool, Any]:
    """Materialize an accepted skill proposal through the canonical Phase 4 publication pipeline."""
    from ..learning.commit_controller import CommitController
    from ..skills.authoring import LocalSkillProposal, PublicationReceipt, SkillAuthoringIntent
    from ..skills.factory import SkillFactory, _slug
    from ..skills.loader import load_builtins, load_domain_skills
    from ..skills.scope import compute_workspace_key, resolve_scope_and_overlap

    store = SkillProposalStore(db_path)
    conn = store._connect()
    try:
        row = conn.execute(
            """SELECT p.state proposal_state, c.*
               FROM skill_proposals p JOIN skill_candidates c
               ON c.candidate_id=p.candidate_id WHERE p.proposal_id=?""",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return False, f"proposal '{proposal_id}' not found"
        if (
            row["proposal_state"] != ProposalState.ACCEPTED.value
            and row["state"] != ProposalState.ACCEPTED.value
        ):
            return (
                False,
                f"proposal '{proposal_id}' is not in accepted state (current: {row['proposal_state']})",
            )

        try:
            steps = tuple(store._json_list(row["steps"]))
            tools = tuple(store._json_list(row["tool_names"]))
        except Exception as exc:
            return False, f"invalid candidate payload: {exc}"

        target_scope = row["scope"]
        display_name = row["display_name"]
        intent_text = row["intent"]
    finally:
        conn.close()

    from .skill_need import _DANGEROUS_TOOLS
    from ..skills.model import BANNED_ACTIONS

    dangerous = set(tools) & (_DANGEROUS_TOOLS | BANNED_ACTIONS)
    if dangerous:
        return False, f"skill authoring rejected: dangerous or banned tools {sorted(dangerous)}"

    ws_key = compute_workspace_key(workspace_path)
    existing_skills = load_domain_skills(home, workspace=workspace_path)
    builtins = load_builtins()

    authoring_intent = SkillAuthoringIntent(
        operation="create",
        capability=display_name or intent_text,
        target_scope=target_scope,
        referenced_name=display_name,
        local_only=True,
        requires_research=False,
        confidence=1.0,
        raw_prompt=intent_text,
        desired_disposition=desired_disposition,
    )

    resolution = resolve_scope_and_overlap(authoring_intent, ws_key, existing_skills, builtins)
    if resolution.status == "REJECTED":
        return False, f"skill authoring rejected: {resolution.reason}"
    if resolution.status == "CLARIFICATION_REQUIRED":
        return False, f"skill authoring requires clarification: {resolution.reason}"

    target_name = resolution.target_name or _slug(display_name)
    when_to_use = f"When the task intent is {intent_text}."
    triggers = (intent_text, display_name)
    verification = ("Verify produced output against requirements.",)

    local_proposal = LocalSkillProposal(
        name=target_name,
        domain="general",
        intent=intent_text,
        scope=resolution.target_scope or target_scope or "global",
        steps=steps,
        required_tools=tools,
        when_to_use=when_to_use,
        triggers=triggers,
        verification=verification,
    )

    factory = SkillFactory()
    draft = factory.build_from_proposal(local_proposal, resolution, existing_skills)

    controller = CommitController(home=home)
    ok, receipt_or_msg = controller.commit_skill_draft(
        draft,
        workspace_key=ws_key,
        desired_disposition=desired_disposition,
    )
    return ok, receipt_or_msg
