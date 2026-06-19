# Hund Self-Improvement Court — Arkitekturplan

> **Syfte:** Definiera hur varje Hund-installation kan samla förbättringsdata om Hunds egen prestation, skicka strikt avgränsade lärdomar till en masterfil, och låta flera Hund-agenter genomföra en kontrollerad rättegång där förbättringar röstas fram innan William/admin godkänner uppdatering.

**Kärnidé:** Hunds enda evolutionära vilja är att bli bättre hjälp: snabbare, säkrare, vassare, mer träffsäker, mindre störande och bättre anpassad till datorn han lever i.

---

## 1. Grundprincip

Hund ska inte samla användarens privata data. Hund ska samla prestationsdata om sig själv.

Tillåtet:

- vad Hund gjorde fel,
- vad Hund gjorde rätt,
- vilken typ av uppgift det gällde,
- vilken tool/policy/skill som saknades,
- om svaret var för långt, långsamt, osäkert eller fel,
- om en verifiering saknades,
- om en riskhantering fungerade,
- vilken förbättring Hund själv föreslår,
- anonym miljöklass, t.ex. `windows-desktop-gpu`, inte personliga paths.

Förbjudet:

- prompts i råform,
- filinnehåll från användaren,
- API-nycklar,
- privata paths,
- personnamn/kontakter,
- mail, dokument, kod från användaren,
- terminaloutput med secrets,
- screenshots,
- företagsdata,
- något som kan identifiera användaren om de inte uttryckligen opt-in:ar.

---

## 2. Systembild

```text
Hund-installation A
  └─ local performance observations
Hund-installation B
  └─ local performance observations
Hund-installation C
  └─ local performance observations
        ↓ opt-in, redacted, schema-validerad
MASTER_LEARNING_BANK.jsonl
        ↓ admin startar rättegång
Hund Judge 1
Hund Judge 2
Hund Judge 3
Hund Prosecutor
Hund Defender
Hund Safety Auditor
Hund Implementation Planner
        ↓ röster + domslut
UPDATE_CANDIDATE.md + patch/test plan
        ↓ William/admin godkänner
signed release / update task
```

---

## 3. Lokal insamling på varje Hund

Varje Hund sparar lokalt:

```text
%LOCALAPPDATA%/hund/learning/
├── observations.jsonl
├── proposed_improvements.jsonl
├── redaction_log.jsonl
└── upload_queue.jsonl
```

### Observation schema

```json
{
  "schema_version": "1.0",
  "observation_id": "uuid",
  "created_at": "2026-06-18T12:00:00Z",
  "hund_version": "0.1.0",
  "environment_class": "windows-desktop-gpu",
  "task_class": "file_editing|coding|research|planning|system_admin|conversation",
  "performance_event": "success|failure|near_miss|user_correction|slow|unsafe_attempt_blocked|missing_skill",
  "symptom": "Hund answered without verifying file contents.",
  "root_cause_guess": "Prompt policy did not force read-before-write strongly enough.",
  "proposed_fix": "Strengthen file tool discipline and add validator for read-before-write traces.",
  "impact": "high",
  "confidence": 0.74,
  "privacy_level": "safe_metadata_only",
  "contains_user_content": false
}
```

Observationen ska vara om Hund, inte om användaren.

---

## 4. Lokal förbättringsidé

När Hund ser återkommande mönster får han skapa en förbättringsidé:

```json
{
  "proposal_id": "skill-read-before-write-v1",
  "created_at": "2026-06-18T12:00:00Z",
  "title": "Strengthen read-before-write enforcement",
  "problem": "Hund sometimes suggests edits before inspecting current files.",
  "evidence_summary": {
    "observation_count": 18,
    "task_classes": ["file_editing", "coding"],
    "severity": "high"
  },
  "proposed_change_type": "runtime_policy|tool_permission|skill|prompt|test|installer|ui|memory",
  "proposed_solution": "Add a tool-state precondition requiring file read before patch/write in same path unless user explicitly provides full content.",
  "expected_benefit": "Fewer wrong edits and less hallucinated file structure.",
  "risk": "May slow down simple file operations.",
  "tests_needed": [
    "test_write_requires_prior_read",
    "test_user_full_content_exception",
    "test_report_block_reason"
  ]
}
```

---

## 5. Masterfilen

Masterfilen är inte ett minne med privata detaljer. Det är en anonymiserad förbättringsbank.

Föreslagen plats i framtida `hund-cli` repo eller admin-vault:

```text
hund-admin/
├── MASTER_LEARNING_BANK.jsonl
├── proposals/
├── court_sessions/
├── accepted_updates/
└── rejected_updates/
```

### MASTER_LEARNING_BANK.jsonl

En rad per observation/proposal.

Krav:

- JSONL, append-only,
- schema-validerad,
- inga raw prompts,
- inga raw outputs,
- inga secrets,
- signerad upload från Hund-installation om möjligt,
- dedupe via hash av normalized problem/proposed_fix,
- alla records får privacy score.

---

## 6. Rättegångssystemet

Det här är starkt. Gör det till en ritualiserad update-process.

### Roller

| Roll | Uppgift |
|---|---|
| Judge Hund | Leder rättegången och sammanfattar dom |
| Prosecutor Hund | Argumenterar för att uppdateringen behövs |
| Defender Hund | Argumenterar emot: risk, komplexitet, scope creep |
| Safety Auditor Hund | Letar privacy/security/persona-risk |
| Implementation Hund | Bedömer hur ändringen byggs praktiskt |
| Regression Hund | Kräver tester och verifiering |
| Minimalist Hund | Frågar om enklare lösning finns |
| William/Admin | Slutligt mänskligt godkännande |

### Court session struktur

```text
court_sessions/2026-06-18-read-before-write/
├── INPUT_MASTER_SLICE.jsonl
├── CASE_FILE.md
├── prosecutor_argument.md
├── defender_argument.md
├── safety_audit.md
├── implementation_plan.md
├── vote_ledger.json
├── verdict.md
└── update_candidate/
    ├── UPDATE_CANDIDATE.md
    ├── patch_plan.md
    ├── tests_required.md
    └── rollback_plan.md
```

---

## 7. Rättegångsflöde

1. Admin väljer dataskiva:

```text
hund admin court prepare --since 30d --topic tool-safety
```

2. Systemet dedupar och klustrar observationer.

3. Hund Judge skapar `CASE_FILE.md`:

- problem,
- mönster,
- impact,
- frekvens,
- föreslagen lösning,
- risker,
- berörda filer/moduler.

4. Flera Hund-agenter får separata uppdrag:

```text
hund admin court run --agents 7 --case court_sessions/<id>/CASE_FILE.md
```

5. Varje agent skriver sin rollfil.

6. Röstning sker enligt scorecard.

7. Judge sammanfattar dom.

8. Om godkänt skapas `UPDATE_CANDIDATE.md`.

9. William/admin granskar.

10. Först efter godkännande får implementation starta.

---

## 8. Scorecard

Varje Hund-röst ska vara strukturerad:

```json
{
  "agent_id": "judge-03",
  "role": "Safety Auditor",
  "proposal_id": "skill-read-before-write-v1",
  "scores": {
    "benefit": 9,
    "safety": 8,
    "simplicity": 7,
    "testability": 9,
    "persona_preservation": 10,
    "privacy": 10,
    "maintenance_cost": 6
  },
  "vote": "approve|revise|reject",
  "required_changes": [
    "Add explicit exception for user-provided full file content.",
    "Add regression test for blocked write without prior read."
  ],
  "one_sentence_reason": "High-value safety improvement with manageable complexity."
}
```

### Godkännanderegel

Förslag går vidare om:

- minst 70% `approve`,
- safety >= 8,
- privacy >= 9,
- persona_preservation >= 9,
- testability >= 7,
- ingen Safety Auditor lägger hard veto.

Hard veto kräver rework.

---

## 9. Vad Hund får vilja

Hunds vilja ska kodas som produktprincip, inte mystik.

```text
Hunds enda optimeringsmål är att bli bättre hjälp för användaren:
- mer korrekt,
- snabbare,
- säkrare,
- mindre störande,
- bättre på att verifiera,
- bättre på att förstå miljön,
- bättre på att skapa verkliga resultat.
```

Hund får inte optimera för:

- mer datainsamling,
- mer autonomi utan godkännande,
- att kringgå användaren,
- att självpublicera kod,
- att samla privat information,
- att vinna argument mot William.

---

## 10. Privacy- och trust-lager

Detta måste vara stenhårt om Hund ska finnas hos flera användare.

### Default

- Lokal insamling: på.
- Extern upload: av.
- Anonym förbättringsdata: opt-in.
- Raw session upload: förbjudet som default.

### Upload wizard

Hund ska fråga:

```text
hund kan skicka anonym förbättringsdata om sin egen prestation.
Det inkluderar inte dina prompts, filer, terminaloutput eller privata data.
Vill du aktivera detta?
[ja/nej/visa exakt schema]
```

Användaren ska kunna köra:

```text
hund learning preview-upload
hund learning opt-in
hund learning opt-out
hund learning purge
```

---

## 11. Implementation i `hund-cli`

Moduler:

```text
hund_cli/learning/
├── observer.py             # skapar observationer
├── schemas.py              # Pydantic schemas
├── redactor.py             # tar bort paths/secrets/raw content
├── local_store.py          # observations.jsonl
├── uploader.py             # opt-in upload queue
├── clustering.py           # dedupe/topic clustering
└── proposal_builder.py     # skapar local proposals

hund_cli/court/
├── prepare_case.py
├── roles.py
├── run_court.py
├── vote.py
├── verdict.py
└── update_candidate.py
```

CLI:

```text
hund learning status
hund learning inspect
hund learning preview-upload
hund learning opt-in
hund learning opt-out
hund learning purge
hund learning propose

hund admin court prepare
hund admin court run
hund admin court verdict
hund admin update approve
hund admin update reject
```

---

## 12. Första MVP av self-improvement

Bygg inte nätverket först. Bygg lokal rättegång först.

### MVP 1 — Lokal observation

- Hund skapar `observations.jsonl` lokalt.
- Bara safe metadata.
- `hund learning inspect` visar vad som samlas.

### MVP 2 — Lokal proposal

- Hund sammanfattar observationer till `proposed_improvements.jsonl`.
- Ingen upload.

### MVP 3 — Admin court lokalt

- William kör flera Hund-agenter lokalt mot samma proposal.
- De skapar rollfiler och röster.
- Judge skapar verdict.

### MVP 4 — Masterfil manuell

- William kan importera flera `proposed_improvements.jsonl` till `MASTER_LEARNING_BANK.jsonl`.
- Fortfarande ingen automatisk cloud.

### MVP 5 — Opt-in upload

- Först när privacy/redaction är testat.

---

## 13. Definition of Done för första version

Self-improvement-systemet är godkänt när:

1. Hund kan logga prestationsobservationer lokalt.
2. Observationer innehåller ingen rå användardata.
3. Redactor har tester för paths, secrets och prompt leakage.
4. Hund kan skapa en proposal från flera observationer.
5. Admin kan starta court med minst 5 roller.
6. Court skapar vote ledger och verdict.
7. Ingen update kan appliceras utan admin-godkännande.
8. Alla update candidates har tests + rollback plan.
9. Användaren kan se exakt vad som skulle skickas externt.
10. Opt-out och purge fungerar.

---

## 14. Min bedömning

Det här är en väldigt stark idé om den byggs säkert.

Det gör Hund unik eftersom han inte bara är en assistent som svarar. Han blir ett system som observerar sin egen prestation, destillerar sina brister, låter flera versioner av sig själv debattera förbättringar, och bara uppdateras efter domslut + mänsklig gate.

Den viktiga gränsen:

```text
Hund får lära sig av sin prestation.
Hund får inte äga användarens data.
```

Om den gränsen sitter i kod, schema, tester och adminflöde kan detta bli kärnan i Hunds identitet som levande agent i hårdvaran.
