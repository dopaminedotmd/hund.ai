"""Unit tests for workspace identity management."""
import os
from pathlib import Path

import hund.workspace as workspace_module
from hund.workspace import (
    clear_workspace_cache,
    workspace_id,
)


def test_git_remote_url_stability(tmp_path: Path) -> None:
    clear_workspace_cache()

    # Simulate repo clone A: C:\Projects\oteck
    repo_a = tmp_path / "repo_a"
    git_dir_a = repo_a / ".git"
    git_dir_a.mkdir(parents=True)
    (git_dir_a / "config").write_text(
        '[core]\n\trepositoryformatversion = 0\n[remote "origin"]\n\turl = git@github.com:dopamine/oteck.git\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n',
        encoding="utf-8",
    )

    # Simulate repo clone B: D:\oteck (different path, same remote URL)
    repo_b = tmp_path / "repo_b"
    git_dir_b = repo_b / ".git"
    git_dir_b.mkdir(parents=True)
    (git_dir_b / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/dopamine/oteck.git\n',
        encoding="utf-8",
    )

    id_a = workspace_id(repo_a)
    clear_workspace_cache()
    id_b = workspace_id(repo_b)

    assert id_a.startswith("ws_git_")
    assert id_b.startswith("ws_git_")
    # Both normalize to dopamine/oteck fingerprint
    import hashlib
    expected_hash_a = hashlib.sha256(b"git@github.com:dopamine/oteck").hexdigest()[:16]
    assert id_a == f"ws_git_{expected_hash_a}"


def test_git_same_remote_different_folders(tmp_path: Path) -> None:
    clear_workspace_cache()

    repo1 = tmp_path / "folder_1"
    git_1 = repo1 / ".git"
    git_1.mkdir(parents=True)
    (git_1 / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/hund-ai/hund.git\n',
        encoding="utf-8",
    )

    repo2 = tmp_path / "folder_2"
    git_2 = repo2 / ".git"
    git_2.mkdir(parents=True)
    (git_2 / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/hund-ai/hund.git\n',
        encoding="utf-8",
    )

    id1 = workspace_id(repo1)
    clear_workspace_cache()
    id2 = workspace_id(repo2)

    assert id1 == id2


def test_git_local_without_remote(tmp_path: Path) -> None:
    clear_workspace_cache()

    repo = tmp_path / "local_repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text('[core]\n\tbare = false\n', encoding="utf-8")

    ws1 = workspace_id(repo)
    assert ws1.startswith("ws_local_")

    # File .git/hund_workspace_id should now exist
    id_file = git_dir / "hund_workspace_id"
    assert id_file.exists()
    assert id_file.read_text(encoding="utf-8").strip() == ws1

    # Re-reading with cleared cache must yield the same ID
    clear_workspace_cache()
    ws2 = workspace_id(repo)
    assert ws1 == ws2


def test_non_git_directory(tmp_path: Path, monkeypatch) -> None:
    clear_workspace_cache()

    dir_a = tmp_path / "plain_dir"
    dir_a.mkdir(parents=True)

    # The test runner may place tmp_path under the repository itself.  Make
    # the intended non-git condition explicit, independent of that layout.
    monkeypatch.setattr(workspace_module, "_find_git_dir", lambda _path: None)

    ws1 = workspace_id(dir_a)
    assert ws1.startswith("ws_dir_")

    # Re-reading returns same persistent ID
    clear_workspace_cache()
    ws2 = workspace_id(dir_a)
    assert ws1 == ws2


def test_workspace_caching(tmp_path: Path) -> None:
    clear_workspace_cache()

    test_dir = tmp_path / "cached_dir"
    test_dir.mkdir(parents=True)

    id1 = workspace_id(test_dir)
    # Modify filesystem under test_dir/.hund to prove memory cache is hit
    ws_file = test_dir / ".hund" / "workspace_id"
    if ws_file.exists():
        ws_file.write_text("tampered_id", encoding="utf-8")

    id2 = workspace_id(test_dir)
    assert id1 == id2
