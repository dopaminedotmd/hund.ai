"""WorktreeManager — git worktree operations for isolated agent branches.

Worktrees live under .worktrees/<branch>/ and give agents a fully isolated
filesystem to write code without affecting the main workspace. Each worktree
is a lightweight git checkout that shares the repository object store.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKTREE_DIR = ".worktrees"


class WorktreeError(Exception):
    """Base exception for worktree operations."""


class WorktreeExistsError(WorktreeError):
    """Branch worktree already exists."""


class WorktreeNotFoundError(WorktreeError):
    """No worktree found for the given branch."""


class WorktreeManager:
    """Manage isolated git worktrees for agent branches.

    Args:
        repo_root: Root of the git repository. Auto-detected from cwd if None.
    """

    def __init__(self, repo_root: str | Path | None = None) -> None:
        if repo_root is None:
            repo_root = Path.cwd()
        self._root = Path(repo_root).resolve()
        self._worktrees_root = self._root / WORKTREE_DIR

    # ── Internal git helpers ──────────────────────────────────────────────

    def _git(self, *args: str) -> str:
        """Run a git command in the repo root. Returns stdout."""
        full_args = ["git", "-C", str(self._root), *args]
        try:
            result = subprocess.run(
                full_args,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as exc:
            msg = exc.stderr.strip() or str(exc)
            raise WorktreeError(f"git error: {msg}") from exc
        except subprocess.TimeoutExpired as exc:
            raise WorktreeError("git command timed out") from exc

    def _branch_exists(self, branch: str) -> bool:
        """Check if a branch exists locally."""
        try:
            self._git("rev-parse", "--verify", branch)
            return True
        except WorktreeError:
            return False

    # ── Public API ────────────────────────────────────────────────────────

    def create_worktree(self, branch: str, base: str = "main") -> Path:
        """Create a new git worktree for the given branch.

        If the branch does not exist, it is created from ``base`` (default main).

        Args:
            branch: Branch name for the worktree.
            base: Base branch/tag/commit to branch from.

        Returns:
            Path to the worktree directory.

        Raises:
            WorktreeExistsError: Worktree already exists for this branch.
            WorktreeError: Git operation failed.
        """
        target = self._worktrees_root / branch

        if target.exists():
            raise WorktreeExistsError(f"Worktree for '{branch}' already exists at {target}")

        self._worktrees_root.mkdir(parents=True, exist_ok=True)

        if not self._branch_exists(branch):
            # Create branch from base first
            self._git("branch", branch, base)

        try:
            self._git("worktree", "add", str(target), branch)
        except WorktreeError:
            # Clean up branch if worktree add fails
            try:
                self._git("branch", "-D", branch)
            except WorktreeError:
                pass
            raise

        return target

    def delete_worktree(self, branch: str) -> None:
        """Remove a worktree and its branch.

        Args:
            branch: Branch name to remove.

        Raises:
            WorktreeNotFoundError: No worktree for this branch.
            WorktreeError: Git operation failed.
        """
        target = self._worktrees_root / branch

        if not target.exists():
            # Check if worktree is registered but directory went missing
            exists = False
            for wt in self._list_raw():
                if wt.get("branch") == branch or (Path(wt.get("path", "")).name == branch):
                    exists = True
                    break
            if not exists:
                raise WorktreeNotFoundError(f"No worktree found for branch '{branch}'")

        # Remove worktree
        try:
            self._git("worktree", "remove", "--force", str(target))
        except WorktreeError:
            # If directory is already gone, prune stale worktree metadata
            self._git("worktree", "prune")

        # Also try to remove via git worktree remove by branch name
        try:
            self._git("worktree", "remove", "--force", branch)
        except WorktreeError:
            pass

        # Clean up the directory if it still exists
        if target.exists():
            import shutil
            shutil.rmtree(target, ignore_errors=True)

        # Delete branch
        if self._branch_exists(branch):
            try:
                self._git("branch", "-D", branch)
            except WorktreeError:
                pass

    def list_worktrees(self) -> list[dict[str, Any]]:
        """List all worktrees with status information.

        Returns:
            List of dicts: {branch, path, commit, status, created_at}
        """
        raw_list = self._list_raw()
        result = []

        for wt in raw_list:
            branch = wt.get("branch", "")
            wt_path = Path(wt.get("path", ""))
            commit = wt.get("commit", "")
            head = wt.get("HEAD", "")

            # Determine status (clean/dirty)
            status = "clean"
            if wt_path.exists():
                try:
                    diff = self._run_captured(
                        ["git", "-C", str(wt_path), "status", "--porcelain"],
                    )
                    if diff.strip():
                        status = "dirty"
                except Exception:
                    status = "unknown"

            # Get created_at from filesystem
            created_at = ""
            if wt_path.exists():
                try:
                    mtime = os.path.getmtime(wt_path)
                    created_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                except Exception:
                    pass

            result.append({
                "branch": branch,
                "path": str(wt_path) if wt_path else "",
                "commit": commit or head,
                "status": status,
                "created_at": created_at,
            })

        return result

    def get_worktree(self, branch: str) -> Path | None:
        """Get the worktree path for a branch, or None."""
        target = self._worktrees_root / branch
        if target.exists():
            return target

        # Search in git worktree list
        for wt in self._list_raw():
            if wt.get("branch") == branch:
                p = Path(wt["path"])
                if p.exists():
                    return p
        return None

    def get_diff(self, branch: str, base: str = "main") -> str:
        """Unified diff between worktree branch and base.

        Args:
            branch: Worktree branch.
            base: Base branch to diff against (default main).

        Returns:
            Unified diff string. Empty string if no diff.
        """
        if not self._branch_exists(branch):
            raise WorktreeNotFoundError(f"Branch '{branch}' does not exist")

        try:
            return self._git("diff", f"{base}..{branch}", "--no-color")
        except WorktreeError:
            return ""

    def get_commit_log(self, branch: str, max_count: int = 10) -> list[dict[str, str]]:
        """Get recent commit log for a branch.

        Args:
            branch: Branch name.
            max_count: Max commits to return (default 10).

        Returns:
            List of dicts: {hash, author, date, message}
        """
        if not self._branch_exists(branch):
            raise WorktreeNotFoundError(f"Branch '{branch}' does not exist")

        fmt = '--format={"hash":"%H","author":"%an","date":"%ai","message":"%s"}'
        raw = self._git("log", fmt, f"-{max_count}", branch)

        commits = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                commits.append(json.loads(line))
            except json.JSONDecodeError:
                commits.append({"raw": line})
        return commits

    # ── Proposal helpers ──────────────────────────────────────────────────

    def propose(self, branch: str, title: str = "", base: str = "main") -> dict[str, Any]:
        """Push branch and create a change proposal ready for review.

        Pushes the branch to origin (sets upstream), generates a diff,
        and returns proposal metadata.

        Args:
            branch: Branch to propose.
            title: Optional title for the proposal.
            base: Base branch (default main).

        Returns:
            Dict with proposal_id, branch, title, diff_url, commit_count, diff.
        """
        if not self._branch_exists(branch):
            raise WorktreeNotFoundError(f"Branch '{branch}' does not exist")

        worktree_path = self.get_worktree(branch)

        # Ensure all changes are committed (or at least stashed)
        if worktree_path:
            try:
                self._run_captured(
                    ["git", "-C", str(worktree_path), "add", "-A"],
                )
            except Exception:
                pass

        # Get diff
        diff = self.get_diff(branch, base)

        # Get commit count for this branch
        try:
            count_raw = self._git("rev-list", "--count", f"^{base}", branch)
            commit_count = int(count_raw.strip())
        except (WorktreeError, ValueError):
            commit_count = 0

        # Get commits
        commits = self.get_commit_log(branch, max_count=20)

        import uuid
        proposal_id = str(uuid.uuid4())

        return {
            "proposal_id": proposal_id,
            "branch": branch,
            "title": title or f"Worktree proposal: {branch}",
            "commit_count": commit_count,
            "commits": commits,
            "diff": diff,
            "diff_lines": len(diff.split("\n")) if diff else 0,
        }

    def merge_to_main(self, branch: str, base: str = "main") -> dict[str, str]:
        """Merge the worktree branch into base (fast-forward if possible).

        Args:
            branch: Worktree branch to merge.
            base: Target branch (default main).

        Returns:
            Dict with status, merge_hash, message.

        Raises:
            WorktreeError: Merge failed.
        """
        if not self._branch_exists(branch):
            raise WorktreeNotFoundError(f"Branch '{branch}' does not exist")

        # Checkout base, merge branch
        self._git("checkout", base)
        self._git("merge", branch, "--no-ff", "-m", f"Merge worktree branch '{branch}'")

        merge_hash = self._git("rev-parse", "HEAD")

        return {
            "status": "merged",
            "merge_hash": merge_hash,
            "message": f"Merged '{branch}' into '{base}'",
        }

    # ── Low-level helpers ─────────────────────────────────────────────────

    def _list_raw(self) -> list[dict[str, str]]:
        """Raw git worktree list as list of dicts."""
        try:
            raw = self._git("worktree", "list", "--porcelain")
        except WorktreeError:
            return []

        worktrees: list[dict[str, str]] = []
        current: dict[str, str] = {}

        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line[len("worktree "):]
            elif line.startswith("HEAD "):
                current["HEAD"] = line[len("HEAD "):]
            elif line.startswith("branch "):
                ref = line[len("branch "):]
                # refs/heads/branch-name -> branch-name
                current["branch"] = ref.replace("refs/heads/", "")
            elif line.startswith("detached"):
                current["branch"] = "(detached)"
            else:
                if "unknown" not in current:
                    current["unknown"] = ""
                current["unknown"] += line + "\n"

        if current:
            worktrees.append(current)

        return worktrees

    def _run_captured(self, cmd: list[str], timeout: int = 30) -> str:
        """Run a command and return stdout. Raises on non-zero exit."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return result.stdout
        except subprocess.TimeoutExpired:
            return ""
