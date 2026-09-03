"""File tools — read/search/write/delete/edit, workspace-confined.

SECURITY: alla sökvägar resolvas mot workspace_root och kastar om utanför.
PermissionEngine klassificerar; dubbel-check här = defense-in-depth.
"""
from __future__ import annotations

from dataclasses import dataclass
import collections
import difflib
import fnmatch
import itertools
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Ignoreras vid sökning — undviker att .venv/.git/AppData förorenar resultat eller orsakar oändliga sökningar.
IGNORE_DIRS = {
    ".venv", "venv", ".git", "__pycache__", ".pytest_cache",
    "node_modules", ".idea", ".vscode", "dist", "build", ".mypy_cache",
    "appdata", ".gemini", ".cache", "site-packages", ".rustup", ".cargo",
    "onedrive",
}
IGNORE_DIRS_LOWER = {d.lower() for d in IGNORE_DIRS}

_EXT_LANG_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".json": "json",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".sh": "bash",
    ".bash": "bash",
    ".ps1": "powershell",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".sql": "sql",
    ".env": "text",
    ".txt": "text",
    ".xml": "xml",
}

_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".svgz",
    ".exe", ".dll", ".so", ".dylib", ".bin",
    ".zip", ".tar", ".gz", ".7z", ".bz2",
    ".pdf", ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".pyd", ".db", ".sqlite", ".sqlite3",
}


def _detect_language(path: str) -> str:
    ext = Path(path).suffix.lower()
    return _EXT_LANG_MAP.get(ext, "text")


def _is_binary(path: str, content: str) -> bool:
    ext = Path(path).suffix.lower()
    if ext in _BINARY_EXTENSIONS:
        return True
    if "\x00" in content:
        return True
    return False


_CHANGE_ID_COUNTER = itertools.count(1)


class FileChangeResult(str):
    """Typed JSON-compatible file change result and string-compatible transport."""

    operation: str
    path: str
    status: str
    content_type_or_language: str
    committed_content_or_diff: str
    display_preview: str
    truncated: bool
    redacted: bool
    binary: bool
    error: str | None
    change_id: int
    note: str

    def __new__(
        cls,
        operation: str,
        path: str,
        status: str,
        content_type_or_language: str,
        committed_content_or_diff: str,
        display_preview: str,
        truncated: bool = False,
        redacted: bool = False,
        binary: bool = False,
        error: str | None = None,
        change_id: int | None = None,
        note: str = "",
    ) -> FileChangeResult:
        if status == "failed":
            text = f"[error] {error or 'file operation failed'}"
        elif status == "no_change":
            text = f"inga ändringar i {path}"
        elif status == "modified":
            text = f"ändrade {path}"
        else:
            text = f"skrev {len(committed_content_or_diff)} bytes -> {path}"
        if note and status in ("created", "modified"):
            text += "\n" + note

        instance = super().__new__(cls, text)
        object.__setattr__(instance, "operation", str(operation))
        object.__setattr__(instance, "path", str(path))
        object.__setattr__(instance, "status", str(status))
        object.__setattr__(instance, "content_type_or_language", str(content_type_or_language))
        object.__setattr__(instance, "committed_content_or_diff", str(committed_content_or_diff))
        object.__setattr__(instance, "display_preview", str(display_preview))
        object.__setattr__(instance, "truncated", bool(truncated))
        object.__setattr__(instance, "redacted", bool(redacted))
        object.__setattr__(instance, "binary", bool(binary))
        object.__setattr__(instance, "error", str(error) if error is not None else None)
        cid = change_id if change_id is not None else next(_CHANGE_ID_COUNTER)
        object.__setattr__(instance, "change_id", int(cid))
        object.__setattr__(instance, "note", str(note))
        return instance

    def __repr__(self) -> str:
        return (
            f"FileChangeResult(operation={self.operation!r}, path={self.path!r}, "
            f"status={self.status!r}, content_type_or_language={self.content_type_or_language!r}, "
            f"truncated={self.truncated}, redacted={self.redacted}, binary={self.binary}, error={self.error!r}, change_id={self.change_id})"
        )

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, FileChangeResult):
            return False
        return (
            self.operation == other.operation
            and self.path == other.path
            and self.status == other.status
            and self.content_type_or_language == other.content_type_or_language
            and self.committed_content_or_diff == other.committed_content_or_diff
            and self.display_preview == other.display_preview
            and self.truncated == other.truncated
            and self.redacted == other.redacted
            and self.binary == other.binary
            and self.error == other.error
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "path": self.path,
            "status": self.status,
            "content_type_or_language": self.content_type_or_language,
            "committed_content_or_diff": self.committed_content_or_diff,
            "display_preview": self.display_preview,
            "truncated": self.truncated,
            "redacted": self.redacted,
            "binary": self.binary,
            "error": self.error,
            "change_id": self.change_id,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileChangeResult:
        return cls(
            operation=data.get("operation", "write_file"),
            path=data.get("path", ""),
            status=data.get("status", "failed"),
            content_type_or_language=data.get("content_type_or_language", ""),
            committed_content_or_diff=data.get("committed_content_or_diff", ""),
            display_preview=data.get("display_preview", ""),
            truncated=bool(data.get("truncated", False)),
            redacted=bool(data.get("redacted", False)),
            binary=bool(data.get("binary", False)),
            error=data.get("error"),
            change_id=data.get("change_id"),
            note=data.get("note", ""),
        )


_LATEST_FILE_CHANGE: dict[int, FileChangeResult] = {}
_CHANGE_HISTORY: collections.deque[FileChangeResult] = collections.deque(maxlen=200)
_CHANGES_BY_ID: dict[int, FileChangeResult] = {}
_UNCONSUMED_CHANGES: list[FileChangeResult] = []
_REGISTRY_LOCK = threading.Lock()


def _record_latest_file_change(res: FileChangeResult, session_id: str | None = None) -> None:
    with _REGISTRY_LOCK:
        tid = threading.get_ident()
        ts = time.time()
        sid = session_id or getattr(res, "session_id", None)
        logger.debug(
            "_record_latest_file_change: session_id=%s path=%s thread_id=%s timestamp=%s status=%s change_id=%s",
            sid,
            getattr(res, "path", None),
            tid,
            ts,
            getattr(res, "status", None),
            getattr(res, "change_id", None),
        )
        _LATEST_FILE_CHANGE[tid] = res
        _CHANGE_HISTORY.append(res)
        _CHANGES_BY_ID[res.change_id] = res
        _UNCONSUMED_CHANGES.append(res)


def get_file_change_by_id(change_id: int) -> FileChangeResult | None:
    with _REGISTRY_LOCK:
        return _CHANGES_BY_ID.get(change_id)


def get_last_file_change_result() -> FileChangeResult | None:
    with _REGISTRY_LOCK:
        if _UNCONSUMED_CHANGES:
            return _UNCONSUMED_CHANGES[-1]
        res = _LATEST_FILE_CHANGE.get(threading.get_ident())
        if res is None and _CHANGE_HISTORY:
            return _CHANGE_HISTORY[-1]
        return res


def pop_last_file_change_result(session_id: str | None = None) -> FileChangeResult | None:
    with _REGISTRY_LOCK:
        tid = threading.get_ident()
        ts = time.time()
        if _UNCONSUMED_CHANGES:
            res = _UNCONSUMED_CHANGES.pop(0)
            _LATEST_FILE_CHANGE.pop(tid, None)
        else:
            res = _LATEST_FILE_CHANGE.pop(tid, None)
            if res is None and _CHANGE_HISTORY:
                res = _CHANGE_HISTORY[-1]
        sid = session_id or (getattr(res, "session_id", None) if res else None)
        logger.debug(
            "pop_last_file_change_result: session_id=%s path=%s thread_id=%s timestamp=%s status=%s change_id=%s",
            sid,
            getattr(res, "path", None) if res else None,
            tid,
            ts,
            getattr(res, "status", None) if res else None,
            getattr(res, "change_id", None) if res else None,
        )
        return res


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
        path_str = args.get("path", "")
        try:
            p = _resolve(ws, path_str)
        except ValueError:
            return f"[error] path outside workspace; use the terminal with the user-provided absolute path or request workspace switch: {path_str}"
        if not p.exists():
            return f"[error] file not found: {path_str}"
        if p.is_dir():
            return f"[error] path is a directory: {path_str}"

        try:
            raw_offset = int(args.get("offset", 1))
            offset = 1 if raw_offset < 1 else raw_offset
        except (ValueError, TypeError):
            return f"[error] offset must be an integer, got: {args.get('offset')}"

        limit_arg = args.get("limit")
        if limit_arg is not None:
            try:
                limit = int(limit_arg)
                if limit <= 0:
                    return f"[error] limit must be greater than 0, got: {limit}"
            except (ValueError, TypeError):
                return f"[error] limit must be an integer, got: {limit_arg}"
        else:
            limit = 500

        with p.open("r", encoding="utf-8", errors="replace", newline="") as f:
            lines = f.readlines()
        total_lines = len(lines)

        if total_lines == 0:
            if offset > 1:
                return f"[error] offset {offset} exceeds total lines (0)"
            return ""

        start_idx = offset - 1
        if start_idx >= total_lines:
            return f"[error] offset {offset} exceeds total lines ({total_lines})"

        end_idx = min(start_idx + limit, total_lines)
        selected_lines = lines[start_idx:end_idx]
        content = "".join(selected_lines)

        MAX_CONTENT_CHARS = 49_500
        notice = ""
        if end_idx < total_lines or len(content) > MAX_CONTENT_CHARS:
            if len(content) > MAX_CONTENT_CHARS:
                content = content[:MAX_CONTENT_CHARS]
            notice = f"\n\n[TRUNCATED — showing lines {offset}-{end_idx} of {total_lines}. Use offset={end_idx + 1} to read further.]"

        return content + notice

    def search_files(args: dict) -> str:
        pattern = args.get("pattern", "*")
        try:
            root = _resolve(ws, args.get("path", "."))
        except ValueError:
            return f"[error] path outside workspace; use the terminal with the user-provided absolute path or request workspace switch: {args.get('path', '.')}"
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

    def write_file(args: dict) -> FileChangeResult:
        path_str = args.get("path", "")
        content = args.get("content", "")
        lang = _detect_language(path_str)

        def _html_artifact_note(html_content: str) -> str:
            """Static well-formedness note for generated HTML (agyC/2, Spår 12).

            Parse-level invariants only. Visual/layout correctness needs a real
            browser — the note says so instead of ever claiming 'parse ok'.
            """
            from html.parser import HTMLParser

            errors: list[str] = []

            class _Checker(HTMLParser):
                def __init__(self) -> None:
                    super().__init__(convert_charrefs=True)
                    self.stack: list[str] = []

                def handle_starttag(self, tag, attrs) -> None:
                    if tag not in (
                        "br", "hr", "img", "input", "meta", "link", "source",
                        "wbr", "area", "base", "col", "embed", "param", "track",
                    ):
                        self.stack.append(tag)

                def handle_endtag(self, tag) -> None:
                    if self.stack and self.stack[-1] == tag:
                        self.stack.pop()
                    elif tag in self.stack:
                        while self.stack and self.stack[-1] != tag:
                            errors.append(f"unclosed <{self.stack.pop()}>")
                        if self.stack:
                            self.stack.pop()
                    else:
                        errors.append(f"stray </{tag}>")

            try:
                checker = _Checker()
                checker.feed(html_content)
                for tag in checker.stack:
                    errors.append(f"unclosed <{tag}>")
            except Exception as exc:
                errors.append(f"parse error: {exc}")
            if not errors:
                return (
                    "[html static check: well-formed. Visual/layout correctness "
                    "requires a real browser — do not claim visual ok without it.]"
                )
            return "[html static check: " + "; ".join(errors[:5]) + "]"

        try:
            p = _resolve(ws, path_str)
        except Exception as exc:
            res = FileChangeResult(
                operation="write_file",
                path=path_str,
                status="failed",
                content_type_or_language=lang,
                committed_content_or_diff="",
                display_preview="",
                error=f"invalid path: {exc}",
            )
            _record_latest_file_change(res)
            return res

        builtins_dir = Path(__file__).resolve().parent.parent / "skills" / "builtins"
        try:
            p.resolve().relative_to(builtins_dir.resolve())
            res = FileChangeResult(
                operation="write_file",
                path=path_str,
                status="failed",
                content_type_or_language=lang,
                committed_content_or_diff="",
                display_preview="",
                error=f"write blocked: {path_str} is a protected builtin motor skill",
            )
            _record_latest_file_change(res)
            return res
        except ValueError:
            pass

        binary = _is_binary(path_str, content)
        if binary:
            file_existed = p.exists()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8", errors="replace")
            res = FileChangeResult(
                operation="write_file",
                path=path_str,
                status="created" if not file_existed else "modified",
                content_type_or_language="binary",
                committed_content_or_diff="",
                display_preview=f"[binary content: {path_str}]",
                binary=True,
            )
            _record_latest_file_change(res)
            return res

        file_existed = p.exists()
        old_content = ""
        if file_existed:
            try:
                old_content = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                old_content = ""

        if file_existed and old_content == content:
            status = "no_change"
            committed_or_diff = ""
            preview = ""
        elif file_existed:
            status = "modified"
            diff_lines = list(difflib.unified_diff(
                old_content.splitlines(),
                content.splitlines(),
                fromfile=f"a/{path_str}",
                tofile=f"b/{path_str}",
                lineterm="",
            ))
            committed_or_diff = "\n".join(diff_lines)
            preview = committed_or_diff
        else:
            status = "created"
            committed_or_diff = content
            preview = content

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except Exception as exc:
            res = FileChangeResult(
                operation="write_file",
                path=path_str,
                status="failed",
                content_type_or_language=lang,
                committed_content_or_diff="",
                display_preview="",
                error=str(exc),
            )
            _record_latest_file_change(res)
            return res

        # Truncation check for preview
        truncated = False
        lines = preview.splitlines()
        if len(lines) > 20:
            truncated = True
            preview = "\n".join(lines[:20]) + f"\n+{len(lines) - 20} lines omitted"

        # Redaction check for preview
        from ..learning.redactor import redact_text
        redacted_preview_res = redact_text(preview)
        final_preview = redacted_preview_res.text
        redacted = bool(redacted_preview_res.blocked_fields or "[REDACTED" in final_preview or final_preview != preview)

        # agyC/2 (Spår 12): static well-formedness note carried on the result
        # string only (diff/preview stay clean for UI counts).
        html_note = ""
        if status in ("created", "modified") and path_str.lower().endswith((".html", ".htm")):
            html_note = _html_artifact_note(content)

        res = FileChangeResult(
            operation="write_file",
            path=path_str,
            status=status,
            content_type_or_language=lang,
            committed_content_or_diff=committed_or_diff,
            display_preview=final_preview,
            truncated=truncated,
            redacted=redacted,
            binary=False,
            note=html_note,
        )
        _record_latest_file_change(res)
        return res

    def edit_file(args: dict) -> FileChangeResult:
        path_str = args.get("path", "")
        old_str = args.get("old_str", "")
        new_str = args.get("new_str", "")
        lang = _detect_language(path_str)

        try:
            p = _resolve(ws, path_str)
        except Exception as exc:
            res = FileChangeResult(
                operation="edit_file",
                path=path_str,
                status="failed",
                content_type_or_language=lang,
                committed_content_or_diff="",
                display_preview="",
                error=f"invalid path: {exc}",
            )
            _record_latest_file_change(res)
            return res

        builtins_dir = Path(__file__).resolve().parent.parent / "skills" / "builtins"
        try:
            p.resolve().relative_to(builtins_dir.resolve())
            res = FileChangeResult(
                operation="edit_file",
                path=path_str,
                status="failed",
                content_type_or_language=lang,
                committed_content_or_diff="",
                display_preview="",
                error=f"edit blocked: {path_str} is a protected builtin motor skill",
            )
            _record_latest_file_change(res)
            return res
        except ValueError:
            pass

        if not p.exists() or not p.is_file():
            res = FileChangeResult(
                operation="edit_file",
                path=path_str,
                status="failed",
                content_type_or_language=lang,
                committed_content_or_diff="",
                display_preview="",
                error=f"file not found: {path_str}",
            )
            _record_latest_file_change(res)
            return res

        old_content = p.read_text(encoding="utf-8", errors="replace")
        if old_str not in old_content:
            res = FileChangeResult(
                operation="edit_file",
                path=path_str,
                status="failed",
                content_type_or_language=lang,
                committed_content_or_diff="",
                display_preview="",
                error=f"target string not found in {path_str}",
            )
            _record_latest_file_change(res)
            return res

        new_content = old_content.replace(old_str, new_str, 1)
        if new_content == old_content:
            res = FileChangeResult(
                operation="edit_file",
                path=path_str,
                status="no_change",
                content_type_or_language=lang,
                committed_content_or_diff="",
                display_preview="",
            )
            _record_latest_file_change(res)
            return res

        diff_lines = list(difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"a/{path_str}",
            tofile=f"b/{path_str}",
            lineterm="",
        ))
        diff_text = "\n".join(diff_lines)

        p.write_text(new_content, encoding="utf-8")

        # Truncation check for preview
        truncated = False
        lines = diff_text.splitlines()
        preview = diff_text
        if len(lines) > 20:
            truncated = True
            preview = "\n".join(lines[:20]) + f"\n+{len(lines) - 20} lines omitted"

        from ..learning.redactor import redact_text
        redacted_preview = redact_text(preview)
        final_preview = redacted_preview.text
        redacted = bool(redacted_preview.blocked_fields or "[REDACTED" in final_preview or final_preview != preview)

        res = FileChangeResult(
            operation="edit_file",
            path=path_str,
            status="modified",
            content_type_or_language=lang,
            committed_content_or_diff=diff_text,
            display_preview=final_preview,
            truncated=truncated,
            redacted=redacted,
        )
        _record_latest_file_change(res)
        return res

    def delete_file(args: dict) -> str:
        try:
            p = _resolve(ws, args["path"])
        except ValueError:
            return f"[error] path outside workspace; use the terminal with the user-provided absolute path or request workspace switch: {args.get('path', '')}"
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
        "edit_file": edit_file,
        "delete_file": delete_file,
    }
