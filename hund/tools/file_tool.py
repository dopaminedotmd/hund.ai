"""File tools — read/search/write/delete, workspace-confined.

SECURITY: alla sökvägar resolvas mot workspace_root och kastar om utanför.
PermissionEngine klassificerar; dubbel-check här = defense-in-depth.
"""
from __future__ import annotations

from pathlib import Path

# Ignoreras vid sökning — undviker att .venv/.git förorenar resultat.
IGNORE_DIRS = {
    ".venv", "venv", ".git", "__pycache__", ".pytest_cache",
    "node_modules", ".idea", ".vscode", "dist", "build", ".mypy_cache",
}


def _resolve(workspace: Path, path: str) -> Path:
    """Lös path mot workspace, reject traversal utanför."""
    resolved = (workspace / path).resolve()
    resolved.relative_to(workspace)  # ValueError om utanför
    return resolved


def _ignored(p: Path) -> bool:
    return any(part in IGNORE_DIRS for part in p.parts)


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
        hits = []
        for p in root.rglob(pattern):
            if _ignored(p):
                continue
            hits.append(str(p.relative_to(ws)))
            if len(hits) >= 200:
                break
        return "\n".join(hits) if hits else "(inga träffar)"

    def write_file(args: dict) -> str:
        p = _resolve(ws, args["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"], encoding="utf-8")
        return f"skrev {len(args['content'])} bytes -> {args['path']}"

    def delete_file(args: dict) -> str:
        p = _resolve(ws, args["path"])
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

