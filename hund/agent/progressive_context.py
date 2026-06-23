"""Progressive context discovery — AGENTS.md i subdirs."""
from __future__ import annotations
from pathlib import Path

CONTEXT_FILES = ["AGENTS.md", "CLAUDE.md", ".hermes.md"]
MAX_PARENT_WALK = 5

class SubdirectoryHintTracker:
    """Trackar vilka kataloger som redan kontrollerats for kontextfiler."""
    def __init__(self):
        self._checked: set[Path] = set()

    def discover(self, path_hint: str | Path, workspace_root: Path) -> str | None:
        """Walk up fran path_hint, leta efter CONTEXT_FILES. Returnera innehall eller None."""
        target = (workspace_root / path_hint).resolve() if not Path(path_hint).is_absolute() else Path(path_hint).resolve()
        for i, parent in enumerate([target] + list(target.parents)):
            if i > MAX_PARENT_WALK:
                break
            if parent in self._checked:
                continue
            self._checked.add(parent)
            for cf in CONTEXT_FILES:
                cf_path = parent / cf
                if cf_path.exists() and cf_path.is_file():
                    try:
                        content = cf_path.read_text("utf-8", errors="replace")
                        return f"[context from {cf_path.relative_to(workspace_root).as_posix()}]\n{content[:3000]}"
                    except Exception:
                        pass
        return None
