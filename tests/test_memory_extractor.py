from pathlib import Path

from hund.agent.memory_extractor import extract_and_record_memories
from hund.memory.engine import list_active_memories
from hund.memory.gating import select_memory_bullets
from hund.memory.models import STATUS_DRAFT, STATUS_VERIFIED


def test_explicit_fact_is_verified_and_inference_stays_unapplied(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory" / "memory.db"

    recorded = extract_and_record_memories(
        "Jag heter William och jag föredrar korta svar.",
        inference_candidates=("User probably works at night.",),
        workspace_id="hund-ai",
        evidence_id="turn-1",
        db_path=db_path,
    )

    assert {item.status for item in recorded} == {STATUS_VERIFIED, STATUS_DRAFT}
    assert any(item.statement == "User's name is William" for item in recorded)
    assert any(item.statement == "User prefers korta svar" for item in recorded)

    injected_in_a_new_session = select_memory_bullets(
        db_path=db_path,
        workspace_id="hund-ai",
    )
    assert "User's name is William" in injected_in_a_new_session
    assert "User prefers korta svar" in injected_in_a_new_session
    assert "User probably works at night." not in injected_in_a_new_session


def test_memory_turn_recording_is_idempotent_for_one_evidence_id(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory" / "memory.db"
    kwargs = {
        "workspace_id": "hund-ai",
        "evidence_id": "turn-1",
        "db_path": db_path,
    }

    extract_and_record_memories("My name is William.", **kwargs)
    extract_and_record_memories("My name is William.", **kwargs)

    memories = list_active_memories(include_drafts=True, db_path=db_path)
    assert len(memories) == 1
    assert memories[0].support_count == 1


def test_extract_multiple_facts_fastapi_and_strict_typing(tmp_path: Path) -> None:
    db_path = tmp_path / "memory" / "memory.db"
    user_text = "Kom ihåg att mitt favoritramverk är FastAPI och jag föredrar strikt typning."

    recorded = extract_and_record_memories(
        user_text,
        workspace_id="hund-ai",
        evidence_id="turn-fastapi",
        db_path=db_path,
    )

    verified_statements = [item.statement for item in recorded if item.status == STATUS_VERIFIED]
    assert len(verified_statements) >= 2
    assert any("FastAPI" in s for s in verified_statements)
    assert any("strikt typning" in s for s in verified_statements)

    user_md = (tmp_path / "memory" / "user.md").read_text(encoding="utf-8")
    assert "FastAPI" in user_md
    assert "strikt typning" in user_md

    bullets = select_memory_bullets(db_path=db_path, workspace_id="hund-ai")
    assert any("FastAPI" in b for b in bullets)
    assert any("strikt typning" in b for b in bullets)

