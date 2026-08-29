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
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional
import uuid
from dataclasses import replace

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
from ..skills.lifecycle import run_skill_sandbox_test
from ..skills.model import Skill
from ..skills.validator import validate as validate_skill


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


from ..skills.authoring import PublicationReceipt, SkillDraft
from ..skills.loader import _read_skill_file
from ..skills.publication import FastPublicationGate
from ..skills.storage import SkillStorage
from ..skills.vault import SkillVault


class CommitController:
    """Deterministic Commit Controller policy engine."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        home: Optional[Path] = None,
    ) -> None:
        self.db_path = db_path
        self.home = home

    def _skills_dir(self) -> Path:
        base = self.home if self.home is not None else hund_home()
        return base / "brain" / "skills"

    def _write_skill(self, skill: Skill) -> Path:
        storage = SkillStorage(home=self.home)
        return storage.write_canonical_atomic(skill, workspace_key="global")

    def commit_skill_draft(
        self,
        draft: SkillDraft | Skill,
        *,
        workspace_key: str = "global",
        desired_disposition: str = "auto",
        dry_run_executor: Any = None,
    ) -> tuple[bool, PublicationReceipt | str]:
        """Validate, stage, evaluate, snapshot, and publish a skill draft."""
        if isinstance(draft, Skill):
            draft = SkillDraft(
                action="UPDATE" if draft.version != "1.0.0" else "CREATE",
                skill=draft,
                metadata={},
            )

        skill = draft.skill
        gate = FastPublicationGate()

        # 1. In-memory pre-stage scan (checks 1-7, secret scrubbing, prompt injection neutralization)
        pre_stage_res = gate.pre_stage_scan(skill)
        if not pre_stage_res.passed:
            storage = SkillStorage(home=self.home)
            storage.save_staged_draft(skill, None, workspace_key=workspace_key)
            return False, f"pre-stage validation failed: {'; '.join(pre_stage_res.failure_reasons)}"

        redacted_skill = pre_stage_res.redacted_skill

        # 2. Stage draft to .drafts/<workspace_key>/<name>.json
        storage = SkillStorage(home=self.home)
        staged_path = storage.save_staged_draft(redacted_skill, None, workspace_key=workspace_key)

        # 3. Fast Publication Gate evaluation (checks 8-12 + isolated dry-run)
        gate_report = gate.evaluate(
            redacted_skill,
            staged_path,
            registered_tools=set(),
            pre_stage_checks=pre_stage_res.checks,
            dry_run_executor=dry_run_executor,
        )

        if not gate_report.passed:
            storage.save_staged_draft(redacted_skill, gate_report, workspace_key=workspace_key)
            return False, f"publication gate rejected: {'; '.join(gate_report.failure_reasons)}"

        # 4. Check for existing canonical file -> snapshot prior version on update
        canonical_path = storage.get_canonical_path(redacted_skill.name, redacted_skill.scope, workspace_key)
        existing_skill = _read_skill_file(canonical_path) if canonical_path.exists() else None
        if existing_skill is not None:
            storage.snapshot_prior_version(existing_skill, workspace_key)

        # 5. Materialize active skill atomically to canonical storage
        active_skill = replace(
            redacted_skill,
            lifecycle_state="active",
            status="active",
            vault_state="vaulted",
            personal_skill_xp=0,
        )
        storage.write_canonical_atomic(active_skill, workspace_key)

        # 6. Update vault state
        vault = SkillVault(home=self.home)
        vault.sync_scoped_state([active_skill], workspace_key=workspace_key)

        vault_state = "vaulted"
        limitations: list[str] = []
        if desired_disposition == "equip":
            ok_equip, equip_msg = vault.equip(workspace_key, active_skill.capability_id, active_skill.name)
            if ok_equip:
                vault_state = "equipped"
            else:
                limitations.append(f"Could not equip immediately: {equip_msg}")
        elif desired_disposition == "vault":
            vault_state = "vaulted"

        diff_summary = None
        if existing_skill is not None:
            diff_summary = f"Updated from v{existing_skill.version} to v{active_skill.version}"

        from ..skills.contracts import PublicationReceipt
        receipt = PublicationReceipt(
            publication_receipt_id=active_skill.publication_receipt_id or f"rec_{uuid.uuid4().hex[:12]}",
            lineage_id=active_skill.lineage_id,
            schema_version=active_skill.schema_version,
            artifact_version=active_skill.artifact_version,
            capability_id=active_skill.capability_id,
            skill_name=active_skill.name,
            scope=active_skill.scope,
            publication_status=getattr(active_skill, "publication_status", "published"),
            action="created" if draft.action == "CREATE" else "updated",
            version=active_skill.version,
            lifecycle_state="active",
            vault_state=vault_state,
            personal_skill_xp=0,
            source_count=len(active_skill.source_knowledge_refs),
            validation_checks=tuple(c.check_name for c in gate_report.checks if c.passed),
            diff_summary=diff_summary,
            limitations=tuple(limitations),
            published_at=datetime.now(timezone.utc).isoformat(),
            research_metadata=getattr(active_skill, "research_metadata", None),
        )
        return True, receipt

    def _invalidate_skills_for_knowledge(self, unit_id: str) -> None:
        directory = self._skills_dir()
        if not directory.exists():
            return
        for path in directory.glob("*.json"):
            try:
                skill = Skill.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if unit_id not in {ref.knowledge_id for ref in skill.source_knowledge_refs}:
                continue
            if skill.lifecycle_state in {"active", "proven"}:
                invalid = replace(
                    skill, lifecycle_state="quarantined", status="quarantined",
                    vault_state="vaulted", revalidation_required=True,
                )
            else:
                invalid = replace(
                    skill, lifecycle_state="draft", status="draft",
                    vault_state="vaulted", revalidation_required=True,
                )
            self._write_skill(invalid)

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
        fingerprint = json.dumps(
            {
                "proposition": proposal.proposition,
                "scope": proposal.scope,
                "kind": proposal.kind,
                "evidence_ids": sorted(proposal.evidence_ids),
                "deps": proposal.deps,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        unit_id = f"know_{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:20]}"
        if kdb.get_unit(unit_id, db_path=self.db_path):
            return unit_id, "candidate already stored"
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
            from .ledger import get_event

            evidence = (
                get_event(proposal.evidence_ids[0], db_path=self.db_path)
                if proposal.evidence_ids else None
            )
            award_xp(
                domain=dom,
                event_type=EVENT_DISCOVERY,
                unit_id=unit_id,
                evidence_id=proposal.evidence_ids[0] if proposal.evidence_ids else None,
                session_id=evidence.get("session_id") if evidence else None,
                task_id=evidence.get("turn_id") if evidence else None,
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
        task_id: Optional[str] = None,
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
                    evidence_id=evidence_id,
                    session_id=session_id,
                    task_id=task_id,
                    db_path=self.db_path,
                )
                # 2. Validation Promotion Bonus (+8)
                if promoted_to_validated:
                    award_xp(
                        domain=unit.domain,
                        event_type=EVENT_VALIDATION_PROMOTION,
                        unit_id=unit.id,
                        evidence_id=evidence_id,
                        session_id=session_id,
                        task_id=task_id,
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
            self._invalidate_skills_for_knowledge(unit_id)
        return ok
