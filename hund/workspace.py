"""Workspace identity management.

Provides a stable identifier per repository or project directory so that moving
a repository across local disk paths preserves project memory and context.

Strategy:
1. Git remote origin URL fingerprint (if available) -> identical across clones/paths.
2. Git repository persistent local identifier (.git/hund_workspace_id).
3. Non-git directory persistent identifier (.hund/workspace_id or local registry).
4. Memory-cached per resolved directory path.
"""
from __future__ import annotations

import configparser
import hashlib
import json
import os
from pathlib import Path
import uuid

_WORKSPACE_CACHE: dict[str, str] = {}


def _find_git_dir(start_dir: Path) -> Path | None:
    """Traverse parent directories to locate .git directory or file (for worktrees)."""
    curr = start_dir
    for _ in range(50):
        git_target = curr / ".git"
        if git_target.exists():
            if git_target.is_dir():
                return git_target
            # Worktree pointer file: "gitdir: /path/to/.git/worktrees/..."
            try:
                content = git_target.read_text(encoding="utf-8").strip()
                if content.startswith("gitdir:"):
                    git_dir = Path(content.split(":", 1)[1].strip())
                    if git_dir.exists():
                        return git_dir
            except Exception:
                pass
        parent = curr.parent
        if parent == curr:
            break
        curr = parent
    return None


def _get_git_remote_url(git_dir: Path) -> str | None:
    """Extract origin remote URL from .git/config."""
    config_file = git_dir / "config"
    if not config_file.exists() and git_dir.name != ".git":
        # Check common dir in case of worktree
        config_file = git_dir.parent.parent / "config"

    if not config_file.exists():
        return None

    try:
        cfg = configparser.ConfigParser()
        cfg.read(config_file, encoding="utf-8")
        for section in cfg.sections():
            if section.lower() in ('remote "origin"', "remote 'origin'"):
                url = cfg.get(section, "url", fallback=None)
                if url:
                    return url.strip()
            if section.lower().startswith("remote ") and "origin" in section.lower():
                url = cfg.get(section, "url", fallback=None)
                if url:
                    return url.strip()
    except Exception:
        pass
    return None


def _get_persistent_workspaces_file() -> Path:
    from .paths import hund_home

    home = hund_home()
    home.mkdir(parents=True, exist_ok=True)
    return home / "workspaces.json"


def clear_workspace_cache() -> None:
    """Clear in-memory workspace ID cache (useful in tests)."""
    _WORKSPACE_CACHE.clear()


def workspace_id(path: Path | str | None = None) -> str:
    """Calculate or retrieve the stable workspace ID for the given path.

    If path is None, defaults to current working directory.
    """
    target = Path(path if path is not None else Path.cwd()).resolve()
    target_key = str(target).lower()

    if target_key in _WORKSPACE_CACHE:
        return _WORKSPACE_CACHE[target_key]

    git_dir = _find_git_dir(target)
    if git_dir is not None:
        remote_url = _get_git_remote_url(git_dir)
        if remote_url:
            # Normalize remote URL (strip credentials, lowercase, trailing .git/slashes)
            norm_url = remote_url.strip().lower()
            if norm_url.endswith(".git"):
                norm_url = norm_url[:-4]
            norm_url = norm_url.rstrip("/")
            url_hash = hashlib.sha256(norm_url.encode("utf-8")).hexdigest()[:16]
            ws_id = f"ws_git_{url_hash}"
            _WORKSPACE_CACHE[target_key] = ws_id
            return ws_id

        # Local git repo without remote origin
        local_id_file = git_dir / "hund_workspace_id"
        if local_id_file.exists():
            try:
                stored = local_id_file.read_text(encoding="utf-8").strip()
                if stored:
                    _WORKSPACE_CACHE[target_key] = stored
                    return stored
            except Exception:
                pass

        new_id = f"ws_local_{uuid.uuid4().hex[:16]}"
        try:
            local_id_file.write_text(new_id, encoding="utf-8")
        except Exception:
            pass
        _WORKSPACE_CACHE[target_key] = new_id
        return new_id

    # Non-git directory
    local_hund_dir = target / ".hund"
    local_id_file = local_hund_dir / "workspace_id"
    if local_id_file.exists():
        try:
            stored = local_id_file.read_text(encoding="utf-8").strip()
            if stored:
                _WORKSPACE_CACHE[target_key] = stored
                return stored
        except Exception:
            pass

    # Check central registry
    registry_file = _get_persistent_workspaces_file()
    registry: dict[str, str] = {}
    if registry_file.exists():
        try:
            registry = json.loads(registry_file.read_text(encoding="utf-8"))
        except Exception:
            registry = {}

    if target_key in registry:
        ws_id = registry[target_key]
        _WORKSPACE_CACHE[target_key] = ws_id
        return ws_id

    # Generate new directory ID and persist
    new_dir_id = f"ws_dir_{uuid.uuid4().hex[:16]}"
    try:
        local_hund_dir.mkdir(parents=True, exist_ok=True)
        local_id_file.write_text(new_dir_id, encoding="utf-8")
    except Exception:
        pass

    registry[target_key] = new_dir_id
    try:
        registry_file.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    except Exception:
        pass

    _WORKSPACE_CACHE[target_key] = new_dir_id
    return new_dir_id
