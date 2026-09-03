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

    if "request" in args:
        raise ValueError(
            "Direct skill creation via 'request' string is not supported. "
            "All skills must be authored through the interactive authoring flow."
        )

    if "skill" not in args or not isinstance(args.get("skill"), dict):
        raise ValueError("create_skill arguments must include 'skill' dictionary.")

    session_id = str(args.get("session_id", "")).strip() or None
    payload_hash = str(args.get("payload_hash", "")).strip() or None
    authorization_id = str(args.get("authorization_id", "")).strip() or None

    skill_dict = args["skill"]
    scope = str(skill_dict.get("scope", args.get("target_scope", "global"))).strip().lower()
    if scope not in ("global", "project", "unresolved"):
        scope = "global"

    desired_disp = str(args.get("desired_disposition", "auto")).strip().lower()
    if desired_disp not in ("equip", "vault", "auto"):
        desired_disp = "auto"

    return CreateSkillToolArgs(
        request=None,
        target_scope=scope,
        desired_disposition=desired_disp,
        legacy_skill=skill_dict,
        session_id=session_id,
        payload_hash=payload_hash,
        authorization_id=authorization_id,
    )


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

        if tool_args.legacy_skill is None:
            return ToolResult(
                ToolStatus.ERROR,
                ToolKind.SYSTEM,
                public_error="create_skill requires a valid 'skill' dictionary.",
            )

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

        if (
            session is None
            or auth is None
            or not tool_args.authorization_id
            or not tool_args.payload_hash
            or session.state != AuthoringState.PUBLISHING
            or not auth.is_used
            or auth.authorization_id != tool_args.authorization_id
        ):
            return ToolResult(
                ToolStatus.ERROR,
                ToolKind.SYSTEM,
                public_error=(
                    "Canonical skill publication requires an active authoring session with a consumed, "
                    "exact-draft authorization from user consent."
                ),
            )

        actual_hash = compute_payload_hash(tool_args.legacy_skill)
        if (
            auth.payload_hash != actual_hash
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
    return create_skill
