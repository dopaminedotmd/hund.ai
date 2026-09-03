"""agyD/3 — Gate 3 §2.3: /skills four-group catalog + shared selection model."""
import json
from pathlib import Path

from hund.ui.screen_render import (
    catalog_selectables,
    render_skills,
    skills_lines,
)
from hund.ui.snapshots import (
    CatalogSpecialisation,
    SkillItem,
    SkillProposalItem,
    SkillsSnapshot,
    collect_skills,
)


def _skill(name: str, level: int, percent: int, vault_state: str) -> SkillItem:
    return SkillItem(
        name=name,
        domain="x",
        xp=0,
        level=level,
        tier="Expert",
        percent=percent,
        lifecycle_state="active",
        vault_state=vault_state,
        triggers=(),
        tools=(),
        safety_level="safe",
        provenance=(),
        when_to_use="Usage text",
        scope="global",
    )


def _snapshot() -> SkillsSnapshot:
    equipped = (
        _skill("python-fastapi", 2, 78, "equipped"),
        _skill("react-tui", 2, 62, "equipped"),
    )
    parked = (
        _skill("shopify-liquid", 1, 58, "vaulted"),
        _skill("test-simulation", 1, 65, "vaulted"),
    )
    specs = (
        CatalogSpecialisation(
            "fullstack-builder", 3, 70,
            ("python-fastapi", "react-tui", "shopify-liquid"),
        ),
        CatalogSpecialisation("machine-doctor", 2, 55, ("test-simulation",)),
    )
    proposals = (SkillProposalItem("p1", "api-testing", "project", "deferred"),)
    return SkillsSnapshot(
        equipped=equipped, parked=parked, proposals=proposals, specialisations=specs
    )


def test_catalog_selectables_excludes_spec_member_rows():
    entries = catalog_selectables(_snapshot())
    assert entries == (
        ("skill", 0), ("skill", 1),
        ("spec", 0), ("spec", 1),
        ("vault", 0), ("vault", 1),
        ("proposal", 0),
    )
    # Members (2 extra display rows) never consume a selectable slot.
    assert len(entries) == 7


def test_skills_lines_highlights_spec_row_but_not_member_line():
    lines = skills_lines(_snapshot(), width=80, selected=2)  # spec 0
    text = "\n".join(lines)
    assert "❯ ● fullstack-builder" in text
    assert "      └ python-fastapi · react-tui · shopify-liquid" in text
    # No other row carries the selection marker.
    assert text.count("❯") == 1
    assert "  ○ machine-doctor" in text
    # Selection never lands on a member row: next selectable is vault 0.
    lines_next = skills_lines(_snapshot(), width=80, selected=3)  # spec 1
    assert "❯ ● machine-doctor" in "\n".join(lines_next)


def test_render_skills_catalog_groups_and_footer():
    out = render_skills(_snapshot(), width=80, height=24)
    assert "SKILLS (2)" in out
    assert "SPECIALISATIONS (2)" in out
    assert "VAULT (2)" in out
    assert "PROPOSALS (1)" in out
    assert "[4 skills]" in out
    assert "[active]" in out and "[parked]" in out
    assert "◇ deferred" in out
    assert "└ python-fastapi" in out
    assert "Enter Inspect/Manage" in out and "[n] New" in out
    assert "[←] Back · [Esc/q] Close" in out


def test_render_skills_ascii_fallback():
    out = render_skills(_snapshot(), width=80, height=24, ascii_only=True)
    assert "╔" not in out
    assert out.splitlines()[0].startswith("+")
    assert "<- Back" in out and "[n] New" in out
    # ascii_only swaps the frame chrome; content glyphs stay (same as /stats).
    assert "❯ ●" in out
    assert max(len(line) for line in out.splitlines()) <= 79


def test_render_skills_empty_snapshot_geometry():
    snap = SkillsSnapshot((), ())
    out = render_skills(snap, width=80, height=24)
    assert "(No active skills equipped.)" in out
    assert "(No specialisations yet.)" in out
    assert "(No parked skills.)" in out
    assert "(No skill proposals.)" in out
    assert "[0 skills]" in out
    assert len(out.splitlines()) == 24
    assert max(len(line) for line in out.splitlines()) <= 79
    assert "Esc" in out


def test_render_skills_detail_still_reachable_from_catalog_snapshot():
    snap = _snapshot()
    detail = render_skills(snap, width=80, height=24, detail_name="shopify-liquid")
    assert "SKILL DETAIL · shopify-liquid" in detail
    assert "Procedure:" in detail
    assert "[←] Back" in detail
    # Catalog group headers must not leak into the detail view.
    assert "VAULT (2)" not in detail


def test_collect_skills_derives_specialisations_from_domain(tmp_path: Path):
    """Equipped domains become specialisations whose members span parked skills."""
    skills_dir = tmp_path / "brain" / "skills"
    skills_dir.mkdir(parents=True)
    base = json.loads(
        (Path(__file__).parent.parent / "hund/skills/builtins/git-safety.json")
        .read_text(encoding="utf-8")
    )
    for name, domain in [
        ("python-fastapi", "backend"),
        ("react-tui", "frontend"),
        ("git-ops", "backend"),
        ("shopify-tools", "ecommerce"),
    ]:
        payload = dict(base)
        payload.update(name=name, domain=domain, status="active")
        (skills_dir / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "brain" / "skill_state.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "entries": [
                    {"scope_key": "global", "capability_id": n, "name": n,
                     "vault_state": state, "pinned": False}
                    for n, state in [
                        ("python-fastapi", "equipped"),
                        ("react-tui", "equipped"),
                        ("git-ops", "equipped"),
                        ("shopify-tools", "vaulted"),
                    ]
                ],
            }
        ),
        encoding="utf-8",
    )

    snap = collect_skills(home=tmp_path)
    assert [s.name for s in snap.equipped] == ["git-ops", "python-fastapi", "react-tui"]
    assert [s.name for s in snap.parked] == ["shopify-tools"]
    specs = {spec.name: spec for spec in snap.specialisations}
    assert set(specs) == {"backend", "frontend"}  # parked-only domain: no spec yet
    assert specs["backend"].members == ("git-ops", "python-fastapi")
    # Catalog selection skips member rows for derived specs too.
    entries = catalog_selectables(snap)
    assert entries[3] == ("spec", 0) and entries[4] == ("spec", 1)
    assert ("vault", 0) in entries
