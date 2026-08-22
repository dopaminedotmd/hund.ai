"""Tests for Phase 7: Worktree Autonomy.

Covers WorktreeManager (create, delete, list, diff, log), WorktreeSession,
and integration with connector endpoints.

Note: Full git worktree tests require a real git repository. These tests
create a temporary repo for isolation.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from hund.worktree.manager import (
    WorktreeManager,
    WorktreeError,
    WorktreeExistsError,
    WorktreeNotFoundError,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for worktree testing."""
    repo = tmp_path / "repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@hund.ai"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test Runner"],
        cwd=repo, capture_output=True, check=True,
    )

    # Create initial commit on main
    (repo / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=repo, capture_output=True, check=True,
    )
    # Rename default branch to main
    subprocess.run(
        ["git", "branch", "-m", "master", "main"],
        cwd=repo, capture_output=True, check=True,
    )

    return repo


@pytest.fixture
def manager(git_repo: Path) -> WorktreeManager:
    return WorktreeManager(repo_root=git_repo)


# ── WorktreeManager ────────────────────────────────────────────────────


def test_create_worktree(manager: WorktreeManager):
    path = manager.create_worktree("feature/test-branch")
    assert path.exists()
    assert path.name == "test-branch"


def test_create_worktree_uses_base(manager: WorktreeManager):
    path = manager.create_worktree("feature/from-main", base="main")
    assert path.exists()
    # Verify it's on the correct branch
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "feature/from-main"


def test_create_existing_worktree_raises(manager: WorktreeManager):
    manager.create_worktree("feature/existing")
    with pytest.raises(WorktreeExistsError):
        manager.create_worktree("feature/existing")


def test_list_worktrees(manager: WorktreeManager):
    manager.create_worktree("feature/list-test")
    worktrees = manager.list_worktrees()
    branches = [wt["branch"] for wt in worktrees]
    assert "feature/list-test" in branches


def test_get_worktree(manager: WorktreeManager):
    path = manager.create_worktree("feature/get-test")
    result = manager.get_worktree("feature/get-test")
    assert result is not None
    assert result == path


def test_get_worktree_nonexistent(manager: WorktreeManager):
    result = manager.get_worktree("nonexistent")
    assert result is None


def test_get_diff_empty_initial(manager: WorktreeManager):
    """Branch created from main with no changes should have empty diff."""
    manager.create_worktree("feature/no-diff", base="main")
    diff = manager.get_diff("feature/no-diff", base="main")
    assert diff == ""


def test_get_diff_with_changes(manager: WorktreeManager):
    manager.create_worktree("feature/with-diff", base="main")
    wt_path = manager.get_worktree("feature/with-diff")
    # Make a change in the worktree
    (wt_path / "new_file.txt").write_text("hello worktree")
    subprocess.run(
        ["git", "-C", str(wt_path), "add", "-A"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(wt_path), "commit", "-m", "add new_file.txt"],
        capture_output=True, check=True,
    )
    diff = manager.get_diff("feature/with-diff", base="main")
    assert "+hello worktree" in diff


def test_get_diff_nonexistent_branch(manager: WorktreeManager):
    with pytest.raises(WorktreeNotFoundError):
        manager.get_diff("nonexistent-branch")


def test_get_commit_log_empty(manager: WorktreeManager):
    """New branch has initial commit from main."""
    manager.create_worktree("feature/log-empty", base="main")
    commits = manager.get_commit_log("feature/log-empty", max_count=5)
    # Should have the initial commit
    assert len(commits) >= 1


def test_get_commit_log_with_commits(manager: WorktreeManager):
    manager.create_worktree("feature/log-commits", base="main")
    wt_path = manager.get_worktree("feature/log-commits")
    for i in range(3):
        (wt_path / f"file_{i}.txt").write_text(f"content {i}")
        subprocess.run(
            ["git", "-C", str(wt_path), "add", "-A"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(wt_path), "commit", "-m", f"commit {i}"],
            capture_output=True, check=True,
        )
    commits = manager.get_commit_log("feature/log-commits", max_count=5)
    assert len(commits) >= 3
    assert "commit 2" in commits[0].get("message", "")


def test_get_commit_log_nonexistent(manager: WorktreeManager):
    with pytest.raises(WorktreeNotFoundError):
        manager.get_commit_log("nonexistent")


def test_delete_worktree(manager: WorktreeManager):
    manager.create_worktree("feature/delete-me")
    manager.delete_worktree("feature/delete-me")
    assert manager.get_worktree("feature/delete-me") is None


def test_delete_nonexistent_worktree(manager: WorktreeManager):
    with pytest.raises(WorktreeNotFoundError):
        manager.delete_worktree("nonexistent")


def test_propose_creates_proposal(manager: WorktreeManager):
    manager.create_worktree("feature/propose-test", base="main")
    wt_path = manager.get_worktree("feature/propose-test")
    (wt_path / "proposed.txt").write_text("proposed change")
    subprocess.run(
        ["git", "-C", str(wt_path), "add", "-A"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(wt_path), "commit", "-m", "proposed commit"],
        capture_output=True, check=True,
    )
    proposal = manager.propose("feature/propose-test", title="My Proposal")
    assert proposal["title"] == "My Proposal"
    assert proposal["branch"] == "feature/propose-test"
    assert proposal["commit_count"] >= 1
    assert "diff" in proposal


def test_worktree_status_dirty_detection(manager: WorktreeManager):
    """Check that uncommitted changes show as dirty."""
    manager.create_worktree("feature/dirty-test", base="main")
    wt_path = manager.get_worktree("feature/dirty-test")
    (wt_path / "unstaged.txt").write_text("dirty")

    worktrees = manager.list_worktrees()
    for wt in worktrees:
        if wt["branch"] == "feature/dirty-test":
            assert wt["status"] == "dirty"
            break
    else:
        pytest.fail("Worktree not found in list")


def test_worktree_status_clean_after_commit(manager: WorktreeManager):
    manager.create_worktree("feature/clean-test", base="main")
    wt_path = manager.get_worktree("feature/clean-test")
    (wt_path / "committed.txt").write_text("clean")
    subprocess.run(
        ["git", "-C", str(wt_path), "add", "-A"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(wt_path), "commit", "-m", "clean commit"],
        capture_output=True, check=True,
    )
    # After commit, status should be clean
    worktrees = manager.list_worktrees()
    for wt in worktrees:
        if wt["branch"] == "feature/clean-test":
            assert wt["status"] == "clean"
            break
    else:
        pytest.fail("Worktree not found in list")
