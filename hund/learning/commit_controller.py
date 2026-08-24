"""Commit Controller — deterministic policy gate for autonomous knowledge ingestion and lifecycle transitions.

Enforces:
1. Verifiers must pass before commit.
2. Ingestion starts at 'candidate' (NEVER directly 'validated').
3. Empirical reuse promotes: candidate → supported → validated.
4. Contradictions degrade: supported/candidate → deprecated/retracted.
5. Atomic sync of materialized JSON views under brain/knowledge/<domain>.json.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Optional
import uuid

from ..domains.registry import get_registry
from ..knowledge import db as kdb
from ..knowledge.models import (
    ACTION_CREATE,
    ACTION_DEGRADE,
    ACTION_DEPRECATE,
    ACTION_PROMOTE,
    ACTION_RETRACT,
    KnowledgeUnit,
    STATUS_CANDIDATE,
    STATUS_DEPRECATED,
    STATUS_RETRACTED,
    STATUS_SUPPORTED,
    STATUS_VALIDATED,
)
from ..paths import brain_knowledge_dir, hund_home
from .evaluator import CandidateProposal
from .verifiers import verify_candidate_unit


def sync_domain_json(
    domain: str,
    home: Optional[Path] = None,
    db_path: Path | str | None = None,
) -> None:
    """Materialize active knowledge units into brain/knowledge/<domain>.json with atomic write."""
    base_dir = (home / "brain" / "knowledge") if home else brain_knowledge_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    target_file = base_dir / f"{domain}.json"

    # Fetch all active units for this domain
    units = kdb.list_units(domain=domain, db_path=db_path)
    active_units = [u for u in units if u.status not in (STATUS_DEPRECATED, STATUS_RETRACTED)]

    data = {
        "domain": domain,
        "version": 1,
        "units": [
            {
                "id": u.id,
                "created_at": u.created_at,
                "trigger": u.trigger,
                "rule": u.statement,
                "kind": u.kind,
                "status": u.status,
                "confidence": u.confidence,
                "frequency": u.support_count,
                "last_used": u.last_used,
                "success_count": u.support_count,
                "fail_count": u.contradiction_count,
                "deps": u.deps,
                "source": "learning_engine",
            }
            for u in active_units
        ],
    }

    tmp_file = target_file.with_suffix(f".tmp.{os.getpid()}_{uuid.uuid4().hex[:6]}")
    try:
        content = json.dumps(data, ensure_ascii=False, indent=2)
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, target_file)
    except Exception:
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except Exception:
                pass


class CommitController:
    """Deterministic Commit Controller policy engine."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        home: Optional[Path] = None,
    ) -> None:
        self.db_path = db_path
        self.home = home

    def commit_candidate(
        self,
        proposal: CandidateProposal,
        workspace_deps: Optional[dict[str, str]] = None,
    ) -> tuple[str, str]:
        """Verify and commit a candidate proposal to the knowledge store.

        Returns (unit_id, status_message).
        """
        # 1. Deterministic Verification
        is_valid, msg = verify_candidate_unit(proposal, workspace_deps=workspace_deps)
        if not is_valid:
            return "", f"rejected by verifier: {msg}"

        # 2. Canonicalize Domain
        reg = get_registry()
        raw_dom = proposal.scope.get("id", "general")
        dom = reg.canonicalize(raw_dom) or "general"

        # 3. Create Unit (Starts as STATUS_CANDIDATE — never directly validated!)
        unit_id = f"know_{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc).isoformat()
        unit = KnowledgeUnit(
            id=unit_id,
            domain=dom,
            statement=proposal.proposition,
            trigger="",
            kind=proposal.kind,
            status=STATUS_CANDIDATE,
            confidence=min(0.6, proposal.confidence),  # Cap initial confidence at 0.6
            evidence_ids=proposal.evidence_ids,
            deps=proposal.deps,
            created_at=now,
        )

        kdb.insert_unit(
            unit,
            action=ACTION_CREATE,
            reason="committed as candidate via CommitController",
            evidence_id=proposal.evidence_ids[0] if proposal.evidence_ids else None,
            db_path=self.db_path,
        )

        # 4. Award Discovery XP (+1)
        try:
            from ..domains.xp import award_xp, EVENT_DISCOVERY
            award_xp(
                domain=dom,
                event_type=EVENT_DISCOVERY,
                unit_id=unit_id,
                db_path=self.db_path,
            )
        except Exception:
            pass

        # 5. Sync Materialized View
        sync_domain_json(dom, home=self.home, db_path=self.db_path)
        return unit_id, "stored as candidate knowledge"

    def record_usage_and_validate(
        self,
        unit_id: str,
        success: bool,
        evidence_id: Optional[str] = None,
        session_id: Optional[str] = None,
        is_cross_session: bool = False,
    ) -> None:
        """Record real-world usage of a rule and apply promotion/demotion policy + deterministic XP awards."""
        unit = kdb.get_unit(unit_id, db_path=self.db_path)
        if not unit:
            return

        now = datetime.now(timezone.utc).isoformat()
        old_status = unit.status

        if success:
            unit.support_count += 1
            unit.last_used = now
            unit.confidence = min(1.0, unit.confidence + 0.15)

            promoted_to_validated = False

            # Promotion policy
            if unit.status == STATUS_CANDIDATE and unit.support_count >= 2 and unit.confidence >= 0.7:
                unit.status = STATUS_SUPPORTED
                action = ACTION_PROMOTE
                reason = f"promoted to supported (support_count={unit.support_count}, conf={unit.confidence:.2f})"
            elif unit.status == STATUS_SUPPORTED and unit.support_count >= 4 and unit.confidence >= 0.85:
                unit.status = STATUS_VALIDATED
                unit.last_validated_at = now
                action = ACTION_PROMOTE
                reason = f"promoted to validated (support_count={unit.support_count}, conf={unit.confidence:.2f})"
                promoted_to_validated = True
            else:
                action = ACTION_PROMOTE if unit.status != old_status else "support"
                reason = f"successful reuse (support_count={unit.support_count})"

            kdb.update_unit_status(
                unit_id=unit.id,
                new_status=unit.status,
                action=action,
                reason=reason,
                evidence_id=evidence_id,
                confidence_delta=0.15,
                support_delta=1,
                last_used=now,
                db_path=self.db_path,
            )

            # Deterministic XP Awards
            try:
                from ..domains.xp import (
                    award_xp,
                    EVENT_CROSS_SESSION_REUSE,
                    EVENT_SAME_TASK_REUSE,
                    EVENT_VALIDATION_PROMOTION,
                )
                # 1. Reuse XP (+3 or +5)
                reuse_event = EVENT_CROSS_SESSION_REUSE if is_cross_session else EVENT_SAME_TASK_REUSE
                award_xp(
                    domain=unit.domain,
                    event_type=reuse_event,
                    unit_id=unit.id,
                    session_id=session_id,
                    db_path=self.db_path,
                )
                # 2. Validation Promotion Bonus (+8)
                if promoted_to_validated:
                    award_xp(
                        domain=unit.domain,
                        event_type=EVENT_VALIDATION_PROMOTION,
                        unit_id=unit.id,
                        session_id=session_id,
                        db_path=self.db_path,
                    )
            except Exception:
                pass
        else:
            unit.contradiction_count += 1
            unit.confidence = max(0.0, unit.confidence - 0.3)

            # Demotion policy
            if unit.contradiction_count >= 2 or unit.confidence < 0.4:
                unit.status = STATUS_DEPRECATED
                action = ACTION_DEPRECATE
                reason = f"deprecated due to failure/contradiction (contradiction_count={unit.contradiction_count}, conf={unit.confidence:.2f})"
            else:
                action = ACTION_DEGRADE
                reason = f"failed reuse penalty (conf={unit.confidence:.2f})"

            kdb.update_unit_status(
                unit_id=unit.id,
                new_status=unit.status,
                action=action,
                reason=reason,
                evidence_id=evidence_id,
                confidence_delta=-0.3,
                contradiction_delta=1,
                db_path=self.db_path,
            )

        sync_domain_json(unit.domain, home=self.home, db_path=self.db_path)

    def retract_unit(self, unit_id: str, reason: str, evidence_id: Optional[str] = None) -> bool:
        """Manually or programmatically retract a knowledge unit."""
        unit = kdb.get_unit(unit_id, db_path=self.db_path)
        if not unit:
            return False

        ok = kdb.update_unit_status(
            unit_id=unit_id,
            new_status=STATUS_RETRACTED,
            action=ACTION_RETRACT,
            reason=reason,
            evidence_id=evidence_id,
            confidence_delta=-unit.confidence,
            db_path=self.db_path,
        )
        if ok:
            sync_domain_json(unit.domain, home=self.home, db_path=self.db_path)
        return ok
