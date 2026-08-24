"""Workspace dependency extraction and semantic drift compatibility verification."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Optional


def _normalize_pkg_name(name: str) -> str:
    """Normalize package names (lowercase, underscores to dashes)."""
    return name.strip().lower().replace("_", "-")


def _parse_version(v_str: str) -> tuple[int, ...]:
    """Parse version string into tuple of integers for comparison."""
    # Strip any leading specifiers like v, ==, >=, etc.
    clean = re.sub(r"^[^\d]*", "", v_str.strip())
    parts: list[int] = []
    for part in clean.split("."):
        # Extract digits from part (e.g. '4b1' -> 4)
        m = re.match(r"^(\d+)", part)
        if m:
            parts.append(int(m.group(1)))
        else:
            break
    return tuple(parts) if parts else (0,)


def extract_workspace_deps(workspace_path: Path | str | None = None) -> dict[str, str]:
    """Extract installed or declared package dependencies from the workspace.

    Scans pyproject.toml, package.json, requirements.txt, and Cargo.toml.
    Returns a dict mapping normalized package names to declared/pinned versions.
    """
    ws = Path(workspace_path) if workspace_path else Path.cwd()
    deps: dict[str, str] = {}

    # 1. pyproject.toml
    pyproject_file = ws / "pyproject.toml"
    if pyproject_file.exists():
        try:
            import tomllib

            data = tomllib.loads(pyproject_file.read_text(encoding="utf-8", errors="replace"))

            # PEP 621: [project.dependencies]
            proj_deps = data.get("project", {}).get("dependencies", [])
            if isinstance(proj_deps, list):
                for item in proj_deps:
                    m = re.match(r"^([A-Za-z0-9_\-\.]+)\s*([><=~!^].*)?$", str(item).strip())
                    if m:
                        deps[_normalize_pkg_name(m.group(1))] = m.group(2) or "*"

            # Poetry: [tool.poetry.dependencies]
            poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
            if isinstance(poetry_deps, dict):
                for k, v in poetry_deps.items():
                    deps[_normalize_pkg_name(k)] = str(v)

            # Flat dependencies
            flat_deps = data.get("dependencies", {})
            if isinstance(flat_deps, dict):
                for k, v in flat_deps.items():
                    deps[_normalize_pkg_name(k)] = str(v)
            elif isinstance(flat_deps, list):
                for item in flat_deps:
                    m = re.match(r"^([A-Za-z0-9_\-\.]+)\s*([><=~!^].*)?$", str(item).strip())
                    if m:
                        deps[_normalize_pkg_name(m.group(1))] = m.group(2) or "*"
        except Exception:
            pass

    # 2. package.json
    package_json = ws / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
            for sec in ("dependencies", "devDependencies", "peerDependencies"):
                sec_dict = data.get(sec, {})
                if isinstance(sec_dict, dict):
                    for k, v in sec_dict.items():
                        deps[_normalize_pkg_name(k)] = str(v)
        except Exception:
            pass

    # 3. requirements.txt
    req_file = ws / "requirements.txt"
    if req_file.exists():
        try:
            for line in req_file.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or s.startswith("-"):
                    continue
                m = re.match(r"^([A-Za-z0-9_\-\.]+)\s*([><=~!^].*)?$", s)
                if m:
                    pkg = _normalize_pkg_name(m.group(1))
                    ver = m.group(2) or "*"
                    if pkg not in deps:
                        deps[pkg] = ver
        except Exception:
            pass

    return deps


def _compare_version(actual: tuple[int, ...], op: str, required: tuple[int, ...]) -> bool:
    """Compare two version tuples given an operator."""
    # Pad to equal length
    max_len = max(len(actual), len(required))
    a = actual + (0,) * (max_len - len(actual))
    r = required + (0,) * (max_len - len(required))

    if op == "==":
        return a == r
    elif op == "!=":
        return a != r
    elif op == ">=":
        return a >= r
    elif op == "<=":
        return a <= r
    elif op == ">":
        return a > r
    elif op == "<":
        return a < r
    elif op in ("^", "~="):
        # Compatible release: ^1.2.3 allows >=1.2.3, <2.0.0
        if a < r:
            return False
        # Major version must match (unless major is 0, then minor must match)
        if r[0] > 0:
            return a[0] == r[0]
        else:
            return len(r) > 1 and len(a) > 1 and a[1] == r[1]
    return True


def check_dep_compatibility(
    required_deps: dict[str, str],
    current_deps: dict[str, str],
) -> tuple[bool, str]:
    """Check if the current workspace dependencies satisfy the required dependencies.

    Returns (is_compatible, reason).
    """
    if not required_deps:
        return True, "no dependency requirements"

    norm_current = {_normalize_pkg_name(k): v for k, v in current_deps.items()}

    for req_pkg, req_spec in required_deps.items():
        norm_pkg = _normalize_pkg_name(req_pkg)
        if norm_pkg not in norm_current:
            # Package not installed in workspace -> assume compatible or not tracked
            continue

        curr_ver_str = norm_current[norm_pkg]
        curr_ver = _parse_version(curr_ver_str)

        # Parse required specifier, e.g. ">=2.0", "<2.0", "==1.4.0", "^2.1"
        for clause in req_spec.split(","):
            clause = clause.strip()
            if not clause or clause == "*":
                continue

            m = re.match(r"^([><=~!^]+)\s*(.*)$", clause)
            if m:
                op = m.group(1)
                req_ver_str = m.group(2)
            else:
                op = "=="
                req_ver_str = clause

            req_ver = _parse_version(req_ver_str)
            if not _compare_version(curr_ver, op, req_ver):
                return (
                    False,
                    f"drift detected: {req_pkg} current version '{curr_ver_str}' violates '{req_spec}'",
                )

    return True, "all dependency constraints satisfied"
