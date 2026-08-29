"""Tests for Gate A3: Capability cleanup and scope truth."""
import pytest

from hund.skills.authoring import _clean_capability, detect_explicit_skill_intent


class TestCapabilityCleanup:
    @pytest.mark.parametrize(
        "raw,expected_cleaned",
        [
            ("det här projektets api-release checklist", "api-release checklist"),
            ("detta projekts deploy pipeline", "deploy pipeline"),
            ("this project's database backup", "database backup"),
            ("this repo's release checklist", "release checklist"),
            ("det här repots git workflow", "git workflow"),
            ("detta repos linter rules", "linter rules"),
            ("api release checklist för detta projekt", "api release checklist"),
            ("b2b outreach åt mig", "b2b outreach"),
            ("code review for me", "code review"),
            ("deploy script för mig", "deploy script"),
        ],
    )
    def test_strip_leading_and_trailing_scope_phrases(self, raw: str, expected_cleaned: str):
        cleaned = _clean_capability(raw)
        assert cleaned == expected_cleaned

    def test_preserve_mid_sentence_meaningful_words(self):
        raw = "guide för hur man hanterar detta i python"
        cleaned = _clean_capability(raw)
        assert "detta" in cleaned

    def test_detect_intent_extracts_project_scope_from_leading_possessive(self):
        prompt = "Skapa en skill för det här projektets api-release checklist"
        intent = detect_explicit_skill_intent(prompt)
        assert intent is not None
        assert intent.target_scope == "project"
        assert intent.capability == "api-release checklist"

    def test_detect_intent_english_leading_possessive(self):
        prompt = "Create a skill for this project's deployment pipeline"
        intent = detect_explicit_skill_intent(prompt)
        assert intent is not None
        assert intent.target_scope == "project"
        assert intent.capability == "deployment pipeline"

    def test_skriv_en_skill_intent_and_english_slug(self):
        from hund.skills.scope import _slug

        prompt = "Skriv en skill så att du blir bättre och mer strukturerad när vi skriver planeringsfiler."
        intent = detect_explicit_skill_intent(prompt)
        assert intent is not None
        assert intent.operation == "create"
        assert "planeringsfiler" in intent.capability.lower()

        slug = _slug(intent.capability)
        assert "planning-files" in slug or "planning" in slug
        assert "s-att" not in slug
        assert "b-ttre" not in slug
        assert "n-r-vi" not in slug

    def test_skriv_en_skill_fil_syntax(self):
        from hund.skills.scope import _slug

        prompt = "skriv en skill-fil för databasmigrering"
        intent = detect_explicit_skill_intent(prompt)
        assert intent is not None
        assert intent.operation == "create"
        assert _slug(intent.capability) == "database-migration" or "database" in _slug(intent.capability)

    def test_gor_mig_mer_strukturerad_prompt_produces_clean_slug(self):
        from hund.skills.scope import _slug

        prompt = "Gör en skill så att jag blir bättre och mer strukturerad när vi skriver planeringsfiler"
        intent = detect_explicit_skill_intent(prompt)
        assert intent is not None
        assert intent.operation == "create"

        slug = _slug(intent.capability)
        assert "planning-files" in slug or "planning" in slug
        assert "gor" not in slug
        assert "jag" not in slug
        assert "authoring" not in slug
        assert "b-ttre" not in slug

    def test_b2b_outreach_and_kundsupport_sanitization(self):
        from hund.skills.scope import _slug

        # 1. B2B outreach with trailing dot
        prompt1 = "Gör en skill kring B2B outreach åt mig."
        intent1 = detect_explicit_skill_intent(prompt1)
        assert intent1 is not None
        assert _slug(intent1.capability) == "b2b-outreach"

        # 2. Kundsupport with exclamation mark
        prompt2 = "Skapa en skill gällande kundsupport!"
        intent2 = detect_explicit_skill_intent(prompt2)
        assert intent2 is not None
        assert _slug(intent2.capability) == "customer-support"

        # 3. Release review checklist
        prompt3 = "Create a skill for release review checklists."
        intent3 = detect_explicit_skill_intent(prompt3)
        assert intent3 is not None
        assert _slug(intent3.capability) == "release-review-checklists"

    def test_polite_kan_du_gora_en_skill_intent_and_slug(self):
        from hund.skills.scope import _slug

        prompt = "Kan du göra en skill som gör att du skriver bättre planeringsfiler?"
        intent = detect_explicit_skill_intent(prompt)
        assert intent is not None
        assert intent.operation == "create"
        assert _slug(intent.capability) == "planning-files"
