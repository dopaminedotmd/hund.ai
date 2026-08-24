"""Unit tests for dependency extraction and drift compatibility."""
from pathlib import Path

from hund.learning.deps import check_dep_compatibility, extract_workspace_deps


def test_extract_pyproject_deps(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "demo-app"
version = "0.1.0"
dependencies = [
    "rich>=13.0.0",
    "typer>=0.9.0",
    "pydantic>=2.4.0",
]
""",
        encoding="utf-8",
    )

    deps = extract_workspace_deps(tmp_path)
    assert "rich" in deps
    assert "typer" in deps
    assert "pydantic" in deps
    assert ">=13.0.0" in deps["rich"]


def test_extract_package_json_deps(tmp_path: Path) -> None:
    pkg_json = tmp_path / "package.json"
    pkg_json.write_text(
        """
{
  "name": "web-frontend",
  "dependencies": {
    "react": "^18.2.0",
    "next": "14.1.0"
  },
  "devDependencies": {
    "typescript": "^5.0.0"
  }
}
""",
        encoding="utf-8",
    )

    deps = extract_workspace_deps(tmp_path)
    assert "react" in deps
    assert deps["react"] == "^18.2.0"
    assert "next" in deps
    assert "typescript" in deps


def test_check_dep_compatibility_success() -> None:
    current = {
        "pydantic": "2.46.4",
        "rich": "13.7.0",
        "python": "3.11.8",
    }

    # Satisfied constraints
    req = {
        "pydantic": ">=2.0",
        "rich": ">=13.0",
    }
    is_ok, reason = check_dep_compatibility(req, current)
    assert is_ok is True
    assert "satisfied" in reason


def test_check_dep_compatibility_drift_detected() -> None:
    current = {
        "pydantic": "2.46.4",
    }

    # Old knowledge requiring v1
    req = {
        "pydantic": "<2.0",
    }
    is_ok, reason = check_dep_compatibility(req, current)
    assert is_ok is False
    assert "drift detected" in reason
    assert "pydantic" in reason
