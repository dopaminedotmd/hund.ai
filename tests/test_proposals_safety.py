"""Fas 8 — Self-improvement v1.5 säkerhetstester.

Verifierar:
  - verification_required alltid True
  - rollback_note fält finns och propageras
  - raw file content blockeras ur förslag
  - TCB/core-sökvägar tvingas till deklarativ change_type
  - approve ändrar bara status, applicerar ingenting
"""
from __future__ import annotations

import pytest

from hund.selfimprovement import proposal as P


# ------------------------------------------------------------------ #
# verification_required — alltid True                                 #
# ------------------------------------------------------------------ #

def test_verification_required_always_true():
    """Fas 8: verification_required ska alltid vara True i nya proposals."""
    p = P.build_from_gaps(
        [],
        {"title": "t", "problem": "p", "proposed_change": "c",
         "change_type": "skill", "risk": "low"},
    )
    assert p.verification_required is True


def test_verification_required_cannot_be_forced_false():
    """Även om LLM skickar verification_required=False ska fältet vara True."""
    p = P.build_from_gaps(
        [],
        {"title": "t", "problem": "p", "proposed_change": "c",
         "change_type": "runtime_policy", "risk": "low",
         "verification_required": False},
    )
    assert p.verification_required is True


# ------------------------------------------------------------------ #
# rollback_note                                                       #
# ------------------------------------------------------------------ #

def test_rollback_note_propagated():
    """rollback_note från llm_summary ska finnas i Proposal."""
    note = "Radera den tillagda policy-regeln manuellt."
    p = P.build_from_gaps(
        [],
        {"title": "t", "problem": "p", "proposed_change": "c",
         "change_type": "runtime_policy", "risk": "medium",
         "rollback_note": note},
    )
    assert p.rollback_note == note


def test_rollback_note_empty_if_not_provided():
    p = P.build_from_gaps(
        [],
        {"title": "t", "problem": "p", "proposed_change": "c",
         "change_type": "skill", "risk": "low"},
    )
    assert p.rollback_note == ""


def test_rollback_note_in_markdown():
    """as_markdown ska inkludera rollback-sektionen."""
    note = "Återställ skill-filen från git."
    p = P.build_from_gaps(
        [],
        {"title": "Min skill", "problem": "p", "proposed_change": "c",
         "change_type": "skill", "risk": "low", "rollback_note": note},
    )
    md = p.as_markdown()
    assert "Rollback" in md
    assert note in md


# ------------------------------------------------------------------ #
# Raw file content blockeras                                          #
# ------------------------------------------------------------------ #

def test_raw_file_content_by_field_name_blocked():
    """Fält med namn 'file_content' eller 'raw_content' ska redaktas."""
    big_content = "print('hello')\n" * 50  # > 500 tecken via radbrytning
    p = P.build_from_gaps(
        [],
        {"title": "t", "problem": "p",
         "proposed_change": "c",  # detta är OK (kort)
         "file_content": big_content,  # detta är ett råfilsfält
         "change_type": "skill", "risk": "low"},
    )
    # file_content hamnar inte i proposal-kolumner, men om det gör det ska det vara redacted
    # Testa direkt via _is_raw_file_content
    assert P._is_raw_file_content("file_content", big_content) is True
    assert P._is_raw_file_content("raw_content", big_content) is True


def test_long_multiline_proposed_change_blocked():
    """proposed_change med >500 tecken + radbrytningar = rådata, blockeras."""
    raw = "line\n" * 150  # 750 tecken, 150 rader
    assert P._is_raw_file_content("proposed_change", raw) is True


def test_short_proposed_change_not_blocked():
    """Korta fält utan radbrytningar ska passera."""
    assert P._is_raw_file_content("proposed_change", "Add a new rule") is False


def test_build_from_gaps_blocks_long_proposed_change():
    """Om proposed_change är råinnehåll ska det ersättas med placeholder."""
    raw = "def foo():\n    pass\n" * 40  # > 500 tecken
    p = P.build_from_gaps(
        [],
        {"title": "t", "problem": "p",
         "proposed_change": raw,
         "change_type": "skill", "risk": "low"},
    )
    assert "REDACTED" in p.proposed_change
    assert "def foo" not in p.proposed_change


# ------------------------------------------------------------------ #
# TCB / core-sökvägar                                                 #
# ------------------------------------------------------------------ #

def test_core_change_type_forced_to_runtime_policy():
    """change_type=core tvingas till runtime_policy (TCB-skydd)."""
    p = P.build_from_gaps([], {"change_type": "core"})
    assert p.change_type == "runtime_policy"


def test_engine_change_type_forced():
    p = P.build_from_gaps([], {"change_type": "engine"})
    assert p.change_type == "runtime_policy"


def test_updater_change_type_forced():
    p = P.build_from_gaps([], {"change_type": "updater"})
    assert p.change_type == "runtime_policy"


def test_redactor_change_type_forced():
    p = P.build_from_gaps([], {"change_type": "redactor"})
    assert p.change_type == "runtime_policy"


# ------------------------------------------------------------------ #
# approve ändrar bara status — applicerar ingenting                   #
# ------------------------------------------------------------------ #

def test_set_status_only_updates_db_field():
    """set_status ska bara uppdatera status-fältet; ingen sidoeffekt."""
    p = P.build_from_gaps(
        [],
        {"title": "SafeProposal", "problem": "x", "proposed_change": "y",
         "change_type": "skill", "risk": "low"},
    )
    P.create(p)
    count = P.set_status(p.id[:8], "approved")
    assert count == 1
    fetched = P.get(p.id[:8])
    assert fetched.status == "approved"
    # Verifiera att inga andra fält har ändrats
    assert fetched.title == p.title
    assert fetched.proposed_change == p.proposed_change
    assert fetched.verification_required is True


def test_approve_does_not_create_files(tmp_path):
    """approve-flödet ska inte skapa filer eller köra kommandon."""
    import os
    files_before = set(os.listdir(tmp_path))
    p = P.build_from_gaps([], {"change_type": "skill"})
    P.create(p)
    P.set_status(p.id[:8], "approved")
    files_after = set(os.listdir(tmp_path))
    assert files_before == files_after, "approve fick sidoeffekter på filsystemet!"
