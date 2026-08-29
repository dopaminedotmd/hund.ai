"""Safe persistence boundary for user-authored declarative skills."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..learning.commit_controller import CommitController
from ..skills.authoring import (
    AuthoringState,
    CreateSkillToolArgs,
    PublicationReceipt,
    get_authoring_registry,
    render_publication_receipt,
)
from ..skills.contracts import compute_payload_hash
from ..skills.model import Skill
from ..skills.scope import compute_workspace_key
from .types import ToolKind, ToolResult, ToolStatus, create_success_result


def parse_create_skill_args(args: dict[str, Any]) -> CreateSkillToolArgs:
    """Parse and validate untrusted provider arguments into CreateSkillToolArgs."""
    if not isinstance(args, dict) or not args:
        raise ValueError("create_skill tool arguments must be a non-empty dictionary.")

    has_request = "request" in args and bool(str(args.get("request", "")).strip())
    has_skill = "skill" in args and isinstance(args.get("skill"), dict)

    if has_request and has_skill:
        raise ValueError("Conflicting 'request' and 'skill' fields present; provide one.")

    session_id = str(args.get("session_id", "")).strip() or None
    payload_hash = str(args.get("payload_hash", "")).strip() or None
    authorization_id = str(args.get("authorization_id", "")).strip() or None

    if has_request:
        raw_req = str(args.get("request", "")).strip()
        target_scope = str(args.get("target_scope", "unresolved")).strip().lower()
        if target_scope not in ("global", "project", "unresolved"):
            target_scope = "unresolved"
        desired_disp = str(args.get("desired_disposition", "auto")).strip().lower()
        if desired_disp not in ("equip", "vault", "auto"):
            desired_disp = "auto"
        return CreateSkillToolArgs(
            request=raw_req,
            target_scope=target_scope,
            desired_disposition=desired_disp,
            session_id=session_id,
            payload_hash=payload_hash,
            authorization_id=authorization_id,
        )

    if has_skill:
        skill_dict = args["skill"]
        scope = str(skill_dict.get("scope", args.get("target_scope", "global"))).strip().lower()
        if scope not in ("global", "project", "unresolved"):
            scope = "global"
        return CreateSkillToolArgs(
            request=None,
            target_scope=scope,
            desired_disposition=str(args.get("desired_disposition", "auto")),
            legacy_skill=skill_dict,
            session_id=session_id,
            payload_hash=payload_hash,
            authorization_id=authorization_id,
        )

    raise ValueError("create_skill arguments must include either 'request' string or 'skill' object.")


def make_handler(home: Path | None = None, workspace_path: Path | None = None) -> Callable[[dict], ToolResult]:
    """Build a handler that authoring-resolves, validates, and stores skills in HundHome.

    The model never receives a filesystem path and cannot bypass the
    CommitController by writing a relative ``brain/skills`` file.
    """

    def create_skill(args: dict) -> ToolResult:
        try:
            tool_args = parse_create_skill_args(args)
        except ValueError as exc:
            return ToolResult(
                ToolStatus.ERROR,
                ToolKind.SYSTEM,
                public_error=f"Invalid create_skill arguments: {exc}",
            )

        ws_key = compute_workspace_key(workspace_path)
        controller = CommitController(home=home)

        # 1. Handle Legacy Schema input (structured Skill dict)
        if tool_args.legacy_skill is not None:
            try:
                skill = Skill.from_dict(tool_args.legacy_skill)
            except Exception as exc:
                return ToolResult(
                    ToolStatus.ERROR,
                    ToolKind.SYSTEM,
                    public_error=f"Invalid skill structure: {exc}",
                )

            reg = get_authoring_registry()
            session = reg.get(tool_args.session_id) if tool_args.session_id else None
            auth = session.publication_authorization if session is not None else None

            # If an active UI stepper session is explicitly linked, verify exact-draft authorization
            if session is not None and tool_args.authorization_id:
                actual_hash = compute_payload_hash(tool_args.legacy_skill)
                if (
                    auth is None
                    or session.state != AuthoringState.PUBLISHING
                    or not auth.is_used
                    or auth.authorization_id != tool_args.authorization_id
                    or auth.payload_hash != actual_hash
                    or tool_args.payload_hash != actual_hash
                    or auth.scope != skill.scope
                    or auth.disposition != tool_args.desired_disposition
                ):
                    return ToolResult(
                        ToolStatus.ERROR,
                        ToolKind.SYSTEM,
                        public_error=(
                            "Canonical skill publication requires a consumed, exact-draft "
                            "authorization from the active Ready flow."
                        ),
                    )

            # Auto-ensure mandatory banned actions
            from ..skills.model import BANNED_ACTIONS
            if not set(BANNED_ACTIONS).issubset(set(skill.forbidden_actions)):
                from dataclasses import replace
                skill = replace(skill, forbidden_actions=tuple(sorted(set(skill.forbidden_actions) | BANNED_ACTIONS)))

            # Quality validation for direct un-authorized calls
            if session is None:
                from ..skills.authoring import SkillDraft, run_deterministic_quality_checks
                draft = SkillDraft(action="CREATE", skill=skill)
                q_res = run_deterministic_quality_checks(draft)
                if not q_res.passed:
                    return ToolResult(
                        ToolStatus.ERROR,
                        ToolKind.SYSTEM,
                        public_error=f"Skill quality check failed: {'; '.join(q_res.failures)}",
                    )

            ok, receipt_or_msg = controller.commit_skill_draft(
                skill,
                workspace_key=ws_key,
                desired_disposition=tool_args.desired_disposition,
            )
            if not ok:
                return ToolResult(
                    ToolStatus.ERROR,
                    ToolKind.SYSTEM,
                    public_error=f"Skill validation failed: {receipt_or_msg}",
                )

            # Read-back verification from vault (single source of truth)
            from ..skills.vault import SkillVault
            vault = SkillVault(home=home)
            read_back = vault.find_skill(skill.name, workspace=workspace_path)
            if read_back is None:
                return ToolResult(
                    ToolStatus.ERROR,
                    ToolKind.SYSTEM,
                    public_error=f"Skill persistence verification failed: '{skill.name}' was not found in vault after commit.",
                )

            receipt_text = render_publication_receipt(receipt_or_msg) if isinstance(receipt_or_msg, PublicationReceipt) else str(receipt_or_msg)

            if tool_args.session_id and isinstance(receipt_or_msg, PublicationReceipt):
                try:
                    from ..skills.authoring import transition_session
                    sess = reg.get(tool_args.session_id)
                    if sess is not None:
                        transition_session(sess, AuthoringState.PUBLISHED, receipt=receipt_or_msg, registry=reg)
                except Exception:
                    pass

            return create_success_result(
                ToolKind.SYSTEM,
                f"Saved skill '{skill.name}' in Hund's canonical skill vault; {receipt_text}.",
                metadata={"skill_name": skill.name, "lifecycle_state": "active"},
            )

        # 2. Handle Request String input (direct natural language from chat)
        if tool_args.request:
            from ..skills.authoring_runtime import synthesize_skill_proposal_content
            from ..skills.authoring import SkillDraft, run_deterministic_quality_checks
            from ..skills.scope import _slug

            subject = tool_args.request.strip()
            target_name = _slug(subject)
            when_to_use, steps, triggers, verification = synthesize_skill_proposal_content(
                subject=subject,
                target_name=target_name,
                shaping_answers={},
                workspace_configs=(),
            )
            from ..skills.model import BANNED_ACTIONS
            skill = Skill(
                schema_version=1,
                name=target_name,
                domain="general",
                status="draft",
                triggers=triggers,
                when_to_use=when_to_use,
                steps=steps,
                required_tools=(),
                forbidden_actions=tuple(sorted(BANNED_ACTIONS)),
                safety_level="read_only",
                verification=verification,
                lifecycle_state="active",
                vault_state="vaulted",
                version="1.0.0",
                capability_id=f"general/{target_name}",
                scope=tool_args.target_scope if tool_args.target_scope in ("global", "project") else "project",
                personal_skill_xp=0,
            )
            draft = SkillDraft(action="CREATE", skill=skill)
            q_res = run_deterministic_quality_checks(draft)
            if not q_res.passed:
                return ToolResult(
                    ToolStatus.ERROR,
                    ToolKind.SYSTEM,
                    public_error=f"Skill quality check failed: {'; '.join(q_res.failures)}",
                )

            ok, receipt_or_msg = controller.commit_skill_draft(
                skill,
                workspace_key=ws_key,
                desired_disposition=tool_args.desired_disposition,
            )
            if not ok:
                return ToolResult(
                    ToolStatus.ERROR,
                    ToolKind.SYSTEM,
                    public_error=f"Skill publication failed: {receipt_or_msg}",
                )

            # Read-back verification from vault (single source of truth)
            from ..skills.vault import SkillVault
            vault = SkillVault(home=home)
            read_back = vault.find_skill(skill.name, workspace=workspace_path)
            if read_back is None:
                return ToolResult(
                    ToolStatus.ERROR,
                    ToolKind.SYSTEM,
                    public_error=f"Skill persistence verification failed: '{skill.name}' was not found in vault after commit.",
                )

            receipt_text = render_publication_receipt(receipt_or_msg) if isinstance(receipt_or_msg, PublicationReceipt) else str(receipt_or_msg)
            return create_success_result(
                ToolKind.SYSTEM,
                f"Saved skill '{skill.name}' in Hund's canonical skill vault; {receipt_text}.",
                metadata={"skill_name": skill.name, "lifecycle_state": "active"},
            )

        return ToolResult(
            ToolStatus.ERROR,
            ToolKind.SYSTEM,
            public_error="create_skill requires either a 'request' string or a 'skill' definition dictionary.",
        )
    return create_skill
