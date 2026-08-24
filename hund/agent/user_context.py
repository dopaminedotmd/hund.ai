"""Safe expansion of explicit @context references in user prompts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess


_FILE_REF = re.compile(r"@file(?::|\s+)(?:\"([^\"]+)\"|([^\s]+))")
_MAX_CONTEXT_CHARS = 120_000


@dataclass(frozen=True)
class ContextExpansion:
    prompt: str
    references: tuple[str, ...] = ()
    estimated_tokens: int = 0

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

    if not blocks:
        return ContextExpansion(prompt=user_text)
    prompt = user_text + "\n\n" + "\n\n".join(blocks)
    return ContextExpansion(
        prompt=prompt,
        references=tuple(references),
        estimated_tokens=max(1, len(prompt) // 4),
    )
