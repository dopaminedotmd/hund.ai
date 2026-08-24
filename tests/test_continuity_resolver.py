from hund.learning.continuity import ContinuityResolver


def test_continuity_resolver_pure_plan_generation():
    plan = ContinuityResolver().plan(
        "Fortsätt med vår parser från förra gången",
        {"project": "hund"},
    )
    assert plan.detected
    assert "parser" in plan.content_nouns
    assert len(plan.queries) <= 2


def test_continuity_bounded_search_budget_enforcement():
    plan = ContinuityResolver().plan(
        "Last time we decided parser database migration transport security interface",
        {"project": "hund"},
    )
    assert len(plan.queries) <= 2
    assert len(plan.content_nouns) <= 6
    assert plan.max_results_per_query == 3
    assert plan.max_total_chars == 1500


def test_no_cue_produces_no_search():
    plan = ContinuityResolver().plan("Explain Python dictionaries")
    assert not plan.detected
    assert plan.queries == ()

