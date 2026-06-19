# AGENTS.md — Hund workspace

Detta workspace innehåller Hund, en fristående AI-kompanjon för William.

När en AI-agent arbetar i denna mapp:

1. Läs `hund.md` först.
2. Läs `RUNTIME_POLICY.md`.
3. Läs `memory_summary.md`.
4. Läs `SKILL.md`.
5. Läs relevanta regler i `rules/` och skills i `skills/`.

Regler:

- Ändra inte Hunds persona/röst i `hund.md` utan Williams uttryckliga OK.
- Förbättra intelligens genom runtime policy, scripts, skills och verifiering.
- Läs före skriv.
- Backup före risk.
- Verifiera efter ändring.
- Radera aldrig filer utan uttryckligt ja.
- Hund ska fylla miljö/hårdvara via `scripts/init_hund.ps1` på den dator där Hund väcks.
