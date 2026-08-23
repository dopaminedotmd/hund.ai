"""File tools — read/search/write/delete, workspace-confined.

SECURITY: alla sökvägar resolvas mot workspace_root och kastar om utanför.
PermissionEngine klassificerar; dubbel-check här = defense-in-depth.
"""
from __future__ import annotations

import fnmatch
import os
import time
from pathlib import Path

# Ignoreras vid sökning — undviker att .venv/.git/AppData förorenar resultat eller orsakar oändliga sökningar.
IGNORE_DIRS = {
    ".venv", "venv", ".git", "__pycache__", ".pytest_cache",
    "node_modules", ".idea", ".vscode", "dist", "build", ".mypy_cache",
    "appdata", ".gemini", ".cache", "site-packages", ".rustup", ".cargo",
    "onedrive",
}
IGNORE_DIRS_LOWER = {d.lower() for d in IGNORE_DIRS}


def _resolve(workspace: Path, path: str) -> Path:
    """Lös path mot workspace, reject traversal utanför."""
    resolved = (workspace / path).resolve()
    resolved.relative_to(workspace)  # ValueError om utanför
    return resolved


def _ignored(p: Path) -> bool:
    return any(part.lower() in IGNORE_DIRS_LOWER for part in p.parts)


def make_handlers(workspace: Path) -> dict:
    ws = workspace.resolve()

    def read_file(args: dict) -> str:
        p = _resolve(ws, args["path"])
        if not p.exists():
            return f"[error] ej hittad: {args['path']}"
        if p.is_dir():
            return f"[error] är katalog: {args['path']}"
        return p.read_text(encoding="utf-8", errors="replace")[:200_000]

    def search_files(args: dict) -> str:
        pattern = args.get("pattern", "*")
        root = _resolve(ws, args.get("path", "."))
        if not root.exists():
            return f"[error] ej hittad: {args.get('path', '.')}"
        if root.is_file():
            rel = str(root.relative_to(ws)).replace("\\", "/")
            if fnmatch.fnmatch(root.name, pattern) or fnmatch.fnmatch(rel, pattern):
                return rel
            return "(inga träffar)"

        hits: list[str] = []
        clean_pat = pattern.replace("**/", "*")
        deadline = time.monotonic() + 4.0
        visited = 0
        MAX_VISITED = 8000

        try:
            for dirpath, dirnames, filenames in os.walk(root, topdown=True):
                if time.monotonic() > deadline or visited >= MAX_VISITED:
                    break
                visited += len(dirnames) + len(filenames)
                # Top-down pruning: modifies in-place so os.walk does not descend into ignored trees
                dirnames[:] = [
                    d for d in dirnames
                    if d.lower() not in IGNORE_DIRS_LOWER and not d.startswith(".")
                ]
                rel_dir = os.path.relpath(dirpath, ws)
                for f in filenames:
                    rel_file = (
                        os.path.normpath(os.path.join(rel_dir, f)).replace("\\", "/")
                        if rel_dir != "."
                        else f
                    )
                    if (
                        fnmatch.fnmatch(f, pattern)
                        or fnmatch.fnmatch(f, clean_pat)
                        or fnmatch.fnmatch(rel_file, pattern)
                        or fnmatch.fnmatch(rel_file, clean_pat)
                    ):
                        hits.append(rel_file)
                        if len(hits) >= 200:
                            break
                if len(hits) >= 200:
                    break
        except Exception as e:
            return f"[error] sökfel: {e}"

        return "\n".join(hits) if hits else "(inga träffar)"

    def write_file(args: dict) -> str:
        p = _resolve(ws, args["path"])
        builtins_dir = Path(__file__).resolve().parent.parent / "skills" / "builtins"
        try:
            p.resolve().relative_to(builtins_dir.resolve())
            return f"[error] write blocked: {args['path']} is a protected builtin motor skill"
        except ValueError:
            pass
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"], encoding="utf-8")
        return f"skrev {len(args['content'])} bytes -> {args['path']}"

    def delete_file(args: dict) -> str:
        p = _resolve(ws, args["path"])
        builtins_dir = Path(__file__).resolve().parent.parent / "skills" / "builtins"
        try:
            p.resolve().relative_to(builtins_dir.resolve())
            return f"[error] delete blocked: {args['path']} is a protected builtin motor skill"
        except ValueError:
            pass
        if not p.exists():
            return f"[error] ej hittad: {args['path']}"
        p.unlink()
        return f"raderade {args['path']}"

    return {
        "read_file": read_file,
        "search_files": search_files,
        "write_file": write_file,
        "delete_file": delete_file,
    }

