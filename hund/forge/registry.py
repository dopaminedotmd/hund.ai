"""Staged artifact registry for Forge-verified proposals."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..learning.redactor import redact_text
from ..store.sqlite import connect
from .policy import ForgeEvaluation, ForgeProposal, classify_artifact, valid_transition


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ForgeRegistry:
    """Owns staged/runtime artifact state.

    Forge may create verified artifacts, but this registry applies the policy
    matrix before anything becomes runtime truth.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def _connect(self):
        return connect(self.db_path)

    def cache_evaluation(
        self,
        *,
        idempotency_key: str,
        proposal_id: str,
        tenant_id: str,
        request_redacted: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        conn = self._connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO forge_evaluations (
                idempotency_key, proposal_id, tenant_id, request_redacted,
                response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                idempotency_key,
                proposal_id,
                tenant_id,
                json.dumps(request_redacted, ensure_ascii=False, sort_keys=True),
                json.dumps(response, ensure_ascii=False, sort_keys=True),
                _now(),
            ),
        )
        conn.commit()
        conn.close()

    def get_cached_evaluation(self, idempotency_key: str) -> dict[str, Any] | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT response_json FROM forge_evaluations WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        conn.close()
        return json.loads(row[0]) if row else None

    def stage_verified(
        self,
        *,
        tenant_id: str,
        proposal: ForgeProposal,
        evaluation: ForgeEvaluation,
        payload: dict[str, Any],
        source: str = "real",
    ) -> dict[str, Any]:
        decision = classify_artifact(proposal, extra_text=json.dumps(payload, ensure_ascii=False))
        if evaluation.verdict != "approved":
            state = "forge_rejected"
        elif decision.state == "blocked_tcb":
            state = "blocked_tcb"
        elif decision.policy.auto_stage:
            state = "staged"
        else:
            state = "needs_review"

        if state == "staged" and decision.policy.auto_promote:
            if not valid_transition("staged", "promoted"):
                raise ValueError("invalid transition staged -> promoted")
            state = "promoted"
        elif state == "staged" and not decision.policy.auto_promote:
            state = "needs_review"

        redacted_payload = json.loads(redact_text(json.dumps(payload, ensure_ascii=False)).text)
        artifact_id = str(uuid.uuid4())
        now = _now()
        conn = self._connect()
        existing = conn.execute(
            "SELECT artifact_id FROM forge_artifacts WHERE proposal_id=? AND tenant_id=?",
            (proposal.id, tenant_id),
        ).fetchone()
        if existing:
            artifact_id = existing[0]
        conn.execute(
            """
            INSERT OR REPLACE INTO forge_artifacts (
                artifact_id, proposal_id, tenant_id, artifact_type, change_type,
                scope, risk, source, state, payload_redacted, apply_policy,
                forge_verdict, composite_score, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                COALESCE((SELECT created_at FROM forge_artifacts WHERE artifact_id=?), ?), ?)
            """,
            (
                artifact_id,
                proposal.id,
                tenant_id,
                decision.artifact_type,
                proposal.change_type,
                decision.scope,
                proposal.risk,
                source,
                state,
                json.dumps(redacted_payload, ensure_ascii=False, sort_keys=True),
                json.dumps(decision.policy.to_dict(), ensure_ascii=False, sort_keys=True),
                evaluation.verdict,
                evaluation.composite_score,
                artifact_id,
                now,
                now,
            ),
        )
        conn.commit()
        row = self.get_artifact(artifact_id)
        conn.close()
        return row or {}

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT artifact_id, proposal_id, tenant_id, artifact_type, change_type,
                   scope, risk, source, state, payload_redacted, apply_policy,
                   forge_verdict, composite_score, created_at, updated_at
            FROM forge_artifacts WHERE artifact_id=?
            """,
            (artifact_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return _artifact_row(row)

    def list_artifacts(
        self,
        *,
        tenant_id: str | None = None,
        state: str | None = None,
        include_simulation: bool = True,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if tenant_id:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if state:
            clauses.append("state=?")
            params.append(state)
        if not include_simulation:
            clauses.append("source!='simulation'")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT artifact_id, proposal_id, tenant_id, artifact_type, change_type,
                   scope, risk, source, state, payload_redacted, apply_policy,
                   forge_verdict, composite_score, created_at, updated_at
            FROM forge_artifacts
            """
            + where
            + " ORDER BY created_at DESC",
            tuple(params),
        ).fetchall()
        conn.close()
        return [_artifact_row(row) for row in rows]

    def revoke_training_mandate(self, tenant_id: str) -> int:
        conn = self._connect()
        cur = conn.execute(
            """
            UPDATE forge_artifacts
            SET state='needs_review', updated_at=?
            WHERE tenant_id=? AND state IN ('staged', 'promoted') AND scope='tenant'
            """,
            (_now(), tenant_id),
        )
        conn.commit()
        count = cur.rowcount
        conn.close()
        return count


def _artifact_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "artifact_id": row[0],
        "proposal_id": row[1],
        "tenant_id": row[2],
        "artifact_type": row[3],
        "change_type": row[4],
        "scope": row[5],
        "risk": row[6],
        "source": row[7],
        "state": row[8],
        "payload_redacted": json.loads(row[9]) if row[9] else {},
        "apply_policy": json.loads(row[10]) if row[10] else {},
        "forge_verdict": row[11],
        "composite_score": row[12],
        "created_at": row[13],
        "updated_at": row[14],
    }
