from datetime import datetime, timezone

from hund.domains.xp import EVENT_CROSS_SESSION_REUSE, award_xp
from hund.knowledge.db import insert_unit
from hund.knowledge.models import KnowledgeUnit, STATUS_VALIDATED
from hund.learning.skill_opportunity import detect_skill_opportunities


def test_detector_requires_validated_knowledge_and_unique_events(tmp_path):
    db = tmp_path / "knowledge.db"
    now = datetime.now(timezone.utc).isoformat()
    for index in range(2):
        insert_unit(
            KnowledgeUnit(
                id=f"k{index}", domain="python", statement=f"First verify step {index}",
                trigger="test-code", status=STATUS_VALIDATED, confidence=0.9,
                deps={"intent": "test-code"}, created_at=now,
            ),
            db_path=db,
        )
    assert detect_skill_opportunities("python", "test-code", db) is None
    for index in range(2):
        award_xp(
            domain="python", event_type=EVENT_CROSS_SESSION_REUSE,
            unit_id=f"k{index}", evidence_id=f"e{index}",
            session_id=f"s{index}", task_id=f"t{index}", db_path=db,
        )
    opportunity = detect_skill_opportunities("python", "test-code", db)
    assert opportunity is not None
    assert opportunity.observed_reuse == 2
    assert opportunity.cross_session_reuse == 2

