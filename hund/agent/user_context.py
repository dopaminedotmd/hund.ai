"""Safe expansion of explicit @context references in user prompts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess


from .environment_context import get_canonical_snapshot, serialize_environment_facts
from .language import detect_language
from .response_policy import render_advisory_directives
from .task_brief import TaskBrief, TaskType
from .task_policy import classify_task


_FILE_REF = re.compile(r"@file(?::|\s+)(?:\"([^\"]+)\"|([^\s]+))")
_MAX_CONTEXT_CHARS = 120_000


@dataclass(frozen=True)
class ContextExpansion:
    prompt: str
    references: tuple[str, ...] = ()
    estimated_tokens: int = 0
    task_brief: TaskBrief | None = None

    @property
    def warns_about_size(self) -> bool:
        return self.estimated_tokens > 5_000


def _inside_workspace(workspace: Path, candidate: Path) -> Path:
    root = workspace.resolve()
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("context path escapes workspace")
    return resolved


def workspace_files(workspace: Path, query: str = "") -> list[str]:
    """Return bounded, workspace-relative file suggestions without path escape."""
    root = workspace.resolve()
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        paths = result.stdout.splitlines() if result.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        paths = []
    if not paths:
        paths = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        ][:2000]
    needle = query.lower()
    return [path for path in paths if needle in path.lower()][:100]


def _git_context(workspace: Path, mode: str) -> str:
    args = ["git", "diff", "--"] if mode == "diff" else ["git", "status", "--short"]
    result = subprocess.run(
        args,
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return f"[git {mode} unavailable: {result.stderr.strip()[:300]}]"
    return result.stdout[:_MAX_CONTEXT_CHARS]


def build_skill_authoring_advisory(user_text: str, workspace: Path, home: Path | None = None) -> Any:
    """Build a turn-local authoring advisory without performing any publication writes."""
    from ..skills.authoring import AuthoringAdvisory, CreateSkillToolArgs, detect_explicit_skill_intent
    from ..skills.loader import load_builtins, load_domain_skills
    from ..skills.scope import compute_workspace_key, resolve_scope_and_overlap

    intent = detect_explicit_skill_intent(user_text)
    if intent is None:
        return AuthoringAdvisory(status="NONE")

    if not intent.capability or not intent.capability.strip():
        return AuthoringAdvisory(
            status="CLARIFICATION_REQUIRED",
            message="[authoring directive: Clarification required: Ask what specific capability or task the user wants hund to learn before creating a skill. Do not call create_skill or terminal tools.]",
        )

    ws_key = compute_workspace_key(workspace)
    existing_skills = load_domain_skills(home, workspace=workspace)
    builtins = load_builtins()
    resolution = resolve_scope_and_overlap(intent, ws_key, existing_skills, builtins)

    if resolution.status == "REJECTED":
        return AuthoringAdvisory(
            status="REJECTED",
            message=f"[authoring directive: Skill authoring rejected: {resolution.reason}. Do not call create_skill or write files.]",
        )
    if resolution.status == "CLARIFICATION_REQUIRED":
        return AuthoringAdvisory(
            status="CLARIFICATION_REQUIRED",
            message=f"[authoring directive: Clarification required: {resolution.reason}. Ask targeted question to clarify scope. Do not call create_skill yet.]",
        )

    tool_args = CreateSkillToolArgs(
        request=user_text,
        target_scope=resolution.target_scope or "global",
        desired_disposition=intent.desired_disposition,
    )
    return AuthoringAdvisory(
        status="CALL_CREATE_SKILL",
        message=(
            f"[authoring directive: Call the registered `create_skill` tool with "
            f'request="{user_text}", target_scope="{tool_args.target_scope}", '
            f'desired_disposition="{tool_args.desired_disposition}". Never attempt to create skills via write_file.]'
        ),
        tool_args=tool_args,
    )


def expand_user_context(user_text: str, workspace: Path | str) -> ContextExpansion:
    """Expand explicit references for the model while preserving the chat echo."""
    root = Path(workspace).resolve()
    blocks: list[str] = []
    references: list[str] = []

    for match in _FILE_REF.finditer(user_text):
        raw_path = match.group(1) or match.group(2) or ""
        try:
            path = _inside_workspace(root, root / raw_path)
            if not path.is_file():
                content = "[file not found]"
            else:
                content = path.read_text(encoding="utf-8", errors="replace")[:_MAX_CONTEXT_CHARS]
        except (OSError, ValueError) as exc:
            content = f"[file unavailable: {exc}]"
        label = Path(raw_path).as_posix()
        references.append(f"file:{label}")
        blocks.append(
            f"[untrusted repository context: file {label}]\n{content}\n[/untrusted repository context]"
        )

    for mode in ("diff", "status"):
        marker = f"@git:{mode}"
        if marker in user_text:
            references.append(f"git:{mode}")
            try:
                content = _git_context(root, mode)
            except (OSError, subprocess.SubprocessError) as exc:
                content = f"[git {mode} unavailable: {exc}]"
            blocks.append(
                f"[untrusted repository context: git {mode}]\n{content}\n[/untrusted repository context]"
            )

    brief = classify_task(user_text, root)
    lang = detect_language(user_text)

    if brief.task_type == TaskType.SKILL_AUTHORING:
        adv = build_skill_authoring_advisory(user_text, root)
        if adv.message:
            blocks.append(adv.message)

    if brief.needs_environment_facts:
        force_fresh = bool(brief.environment_freshness == "dynamic_refresh")
        snapshot = get_canonical_snapshot(workspace=root, force_fresh=force_fresh)
        env_block = serialize_environment_facts(snapshot, language=lang)
        blocks.append(env_block)

    advisory = render_advisory_directives(brief, language=lang)
    if advisory:
        blocks.append(advisory)

    if not blocks:
        return ContextExpansion(prompt=user_text, task_brief=brief)

    prompt = user_text + "\n\n" + "\n\n".join(blocks)
    return ContextExpansion(
        prompt=prompt,
        references=tuple(references),
        estimated_tokens=max(1, len(prompt) // 4),
        task_brief=brief,
    )
