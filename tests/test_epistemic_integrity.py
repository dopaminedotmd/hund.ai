from hund.learning.gap_detector import detect_evidence_gaps
from hund.learning.observer import observe_epistemic_gaps
from hund.tools.types import ToolKind, ToolResult, ToolStatus


def test_version_question_creates_deterministic_gap():
    gaps = detect_evidence_gaps("What is the latest supported API version?")
    assert [gap.kind for gap in gaps] == ["version_volatility"]


def test_unknown_symbol_requires_failed_local_search():
    assert detect_evidence_gaps("import NewUnknownApi") == ()
    gaps = detect_evidence_gaps("import NewUnknownApi", local_search_failed=True)
    assert gaps[0].kind == "unknown_symbol"


def test_insufficient_typed_tool_results_create_gap():
    result = ToolResult(ToolStatus.NOT_FOUND, ToolKind.FILE)
    gaps = detect_evidence_gaps("read it", tool_results=[result])
    assert gaps[0].study_target == "not_found"


def test_observer_persists_only_structured_label(tmp_path):
    db = tmp_path / "hund.db"
    ids = observe_epistemic_gaps(
        "latest version token=secret-value", domain="python", db_path=db
    )
    assert len(ids) == 1
    import sqlite3
    with sqlite3.connect(db) as conn:
        symptom = conn.execute("SELECT symptom FROM gap_events").fetchone()[0]
    assert symptom == "epistemic:version_volatility"
    assert "secret-value" not in symptom

