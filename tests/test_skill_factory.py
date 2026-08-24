import json

from hund.knowledge.models import KnowledgeUnit
from hund.learning.commit_controller import CommitController
from hund.learning.skill_opportunity import SkillOpportunity
from hund.skills.factory import SkillFactory
from hund.skills.model import Skill


def _units():
    return [
        KnowledgeUnit(id="k1", domain="python", statement="First run tests", created_at="v1"),
        KnowledgeUnit(id="k2", domain="python", statement="Then verify output", created_at="v2"),
    ]


def _opportunity():
    return SkillOpportunity("python", "test code", ("k1", "k2"), 2, 2, 1.0)


def test_factory_create_then_update_is_pure():
    factory = SkillFactory()
    created = factory.build(_opportunity(), _units())
    assert created.action == "CREATE"
    assert created.skill.capability_id == "python/test-code"
    updated = factory.build(_opportunity(), _units(), [created.skill])
    assert updated.action == "UPDATE"
    assert updated.skill.version == "1.1.0"


def test_commit_controller_is_only_materializer_and_sandbox_is_closed(tmp_path):
    draft = SkillFactory().build(_opportunity(), _units()).skill
    controller = CommitController(home=tmp_path, db_path=tmp_path / "knowledge.db")
    ok, message = controller.commit_skill_draft(draft)
    assert ok
    assert "sandbox required" not in message  # no-tool instruction path
    saved = json.loads(
        (tmp_path / "brain" / "skills" / f"{draft.name}.json").read_text("utf-8")
    )
    assert saved["lifecycle_state"] == "draft"


def test_retracted_knowledge_quarantines_active_skill(tmp_path):
    db = tmp_path / "knowledge.db"
    controller = CommitController(home=tmp_path, db_path=db)
    from hund.knowledge.db import insert_unit
    from hund.knowledge.models import STATUS_VALIDATED
    unit = KnowledgeUnit(
        id="k1", domain="python", statement="First run tests",
        status=STATUS_VALIDATED, created_at="v1",
    )
    insert_unit(unit, db_path=db)
    draft = SkillFactory().build(_opportunity(), _units()).skill
    active = Skill.from_dict({
        **draft.to_dict(), "lifecycle_state": "active", "vault_state": "equipped"
    })
    controller._write_skill(active)
    assert controller.retract_unit("k1", "stale")
    saved = json.loads(
        (tmp_path / "brain" / "skills" / f"{active.name}.json").read_text("utf-8")
    )
    assert saved["lifecycle_state"] == "quarantined"
    assert saved["vault_state"] == "vaulted"
    assert saved["revalidation_required"] is True
