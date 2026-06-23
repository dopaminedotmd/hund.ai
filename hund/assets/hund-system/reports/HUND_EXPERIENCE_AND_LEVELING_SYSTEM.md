# Hund Experience & Leveling System — Arkitekturplan

> **Syfte:** Definiera hur Hund mäter sin egen prestation, specialiserar sig efter användarens miljö och arbete, bygger kompakta kunskapsfiler, levlar upp domäner och omvandlar lokal erfarenhet till säkra förbättringsförslag.

**Kärnidé:** Hund börjar med att förstå var han lever. Därefter lär han sig vad användaren faktiskt gör. När mönstret är tydligt slutar Hund expandera brett och börjar fördjupa sina viktigaste domäner tills han blir extremt vass just där.

---

## 1. Produktkänsla

Hund ska kännas som en lokal varelse som växer i sin maskin.

```text
Första uppstart:
Hund vet nästan ingenting om platsen.

Efter miljöanalys:
Hund vet vilken hårdvara, OS, shell och verktyg han lever i.

Efter användning:
Hund börjar förstå vad användaren gör.

Efter specialisering:
Hund fokuserar på sina kärnområden.

Efter mastery:
Hund har kompakta, hårt tränade kunskapsfiler för just den användaren och miljön.
```

Det ska inte vara kosmetisk gamification. Level ska vara ett uttryck för bevisad nytta.

---

## 2. Grundprinciper

1. Hund mäter prestation, inte privat innehåll.
2. Hund specialiserar sig lokalt per användare och maskin.
3. Windows-Hund prioriterar Windows-förbättringar; Linux-Hund prioriterar Linux-förbättringar.
4. Grundprinciper och säkerhetsförbättringar kan bli globala uppdateringar.
5. Domänkunskap får vara Hund-native och kompakt, inte nödvändigtvis mänskligt vacker.
6. XP ges för verifierad nytta, inte för mycket aktivitet.
7. Skills skapas i exploration. Mastery bygger progress i befintliga domäner.
8. Användaren kan alltid öppna ny domän: “hund, nu börjar vi med X”.

---

## 3. OpenRouter-liknande mätpunkter för Hund

OpenRouter-liknande statistik är rätt inspirationskälla eftersom den mäter request, modell, kostnad, tokens och prestanda. Hund ska utöka detta med kvalitets- och lärandesignaler.

### 3.1 Request-statistik

| Metric | Hund-användning |
|---|---|
| `request_id` | Spårbar session/request utan privat innehåll |
| `timestamp` | Trend över tid |
| `command` | `chat`, `edit`, `doctor`, `learning`, `tool_call` |
| `task_class` | coding, file_ops, research, planning, system_admin, conversation |
| `project_type` | shopify, liquid, windows, prompt_engineering, python, unknown |
| `model_requested` | Vilken modell Hund försökte använda |
| `model_actual` | Vilken modell som faktiskt svarade |
| `provider` | OpenAI/OpenRouter/Anthropic/local/etc |
| `finish_reason` | stop, tool_call, error, length, cancelled |

### 3.2 Token och kostnad

| Metric | Hund-användning |
|---|---|
| `prompt_tokens` | Hur dyr kontexten var |
| `completion_tokens` | Hur långt Hund svarade |
| `total_tokens` | Total request-vikt |
| `reasoning_tokens` | Om provider stödjer det |
| `cached_tokens` | Cacheeffektivitet |
| `cost_estimated` | Förhandskostnad |
| `cost_final` | Faktisk kostnad |
| `cost_per_success` | Viktig kvalitetsmetric |
| `tokens_per_verified_result` | Tokeneffektivitet kopplat till nytta |

### 3.3 Prestanda

| Metric | Hund-användning |
|---|---|
| `latency_ms` | Total svarstid |
| `time_to_first_token_ms` | Hur snabbt Hund börjar svara |
| `generation_ms` | Modellens generationstid |
| `tokens_per_second` | Throughput |
| `tool_latency_ms` | Tid i verktyg |
| `retry_count` | Modell/tool behövde göras om |
| `error_count` | Felrate |
| `timeout_count` | Stabilitet |

### 3.4 Tool-statistik

| Metric | Hund-användning |
|---|---|
| `tool_calls_total` | Hur mycket verktyg användes |
| `tool_calls_by_type` | file, terminal, web, memory, skill |
| `tool_success_rate` | Tool-kvalitet |
| `blocked_risky_calls` | Safety fungerade |
| `approval_requests` | Hur ofta användaren behövde godkänna |
| `approval_denied` | Hund föreslog fel risknivå |
| `read_before_write_ok` | Filpolicy följdes |
| `verification_ran` | Hund verifierade faktiskt |

### 3.5 Kvalitet och lärande

| Metric | Hund-användning |
|---|---|
| `user_correction_count` | Användaren behövde korrigera Hund |
| `repeat_error_count` | Hund gjorde samma fel igen |
| `verified_success` | Test/build/validator passerade |
| `unverified_claim` | Hund påstod något utan bevis |
| `skill_hit` | Rätt skill laddades |
| `skill_miss` | Skill saknades |
| `memory_helped` | Minne hjälpte |
| `memory_noise` | Minne störde |
| `domain_xp_gain` | XP till domän |
| `friction_score` | Hur mycket styrning användaren behövde |
| `trust_delta` | Blev Hund mer eller mindre betrodd i domänen |

---

## 4. Lokal datamodell

```text
%LOCALAPPDATA%/hund/experience/
├── telemetry.jsonl              # OpenRouter-lik request/prestandadata
├── quality_events.jsonl         # korrigeringar, verifiering, fel, success
├── xp_ledger.jsonl              # XP-händelser
├── domains.json                 # identifierade användningsdomäner
├── specialization.json          # exploration/specialization/mastery
├── mastery/
│   ├── shopify_liquid.hundk
│   ├── windows_ops.hundk
│   └── prompt_refinement.hundk
└── reports/
    ├── daily_summary.md
    └── weekly_self_review.md
```

---

## 5. Domain detection

Hund ska klassificera vad användaren faktiskt gör.

### Signaler

| Signal | Exempel |
|---|---|
| Filtyper | `.liquid`, `.ps1`, `.py`, `.tsx`, `.md` |
| Kommandon | `shopify theme`, `npm`, `git`, `powershell` |
| Ord i uppgifter | “section”, “prompt”, “Windows”, “theme”, “deploy” |
| Tool usage | många file edits, terminal builds, web research |
| Feltyper | Liquid schema error, PowerShell encoding, API auth |
| Feedback | “så här gör man i Shopify”, “du glömde schema” |

### Domain schema

```json
{
  "domain_id": "shopify_liquid",
  "display_name": "Shopify Liquid",
  "confidence": 0.92,
  "mode": "mastery",
  "level": 6,
  "xp": 642,
  "xp_to_next_level": 800,
  "evidence": {
    "task_count": 71,
    "verified_successes": 44,
    "user_corrections": 9,
    "recent_activity_days": 18
  },
  "soft_locked": true,
  "last_seen": "2026-06-18T12:00:00Z"
}
```

---

## 6. Exploration, Specialization, Mastery

### 6.1 Exploration

Hund observerar brett.

Regler:

- skapa kandidatdomäner,
- skapa kandidat-skills,
- samla mönster,
- fråga inte för ofta,
- undvik att låsa för tidigt.

Trigger till Specialization:

```text
domain_confidence > 0.75
AND task_count >= 20
AND recent_activity >= 5 dagar
AND användaren inte har markerat domänen som tillfällig
```

### 6.2 Specialization

Hund väljer 3–7 kärnområden.

Exempel:

```text
Windows Operations
Shopify Liquid
Prompt Refinement
Safe File Editing
```

Regler:

- 80% learning-budget går till kärnområden,
- 20% går till omvärldsbevakning av nya mönster,
- Hund föreslår soft lock för användaren.

### 6.3 Mastery

Hund bygger djup kunskap i domänen.

Regler:

- skapa inte ny skill för varje lärdom,
- lägg erfarenhet i `.hundk`,
- uppdatera XP/progress,
- mät förbättring över tid,
- skapa global proposal bara om principen kan hjälpa alla.

---

## 7. Soft lock

Soft lock betyder att Hund fokuserar, inte att Hund blir blind.

```json
{
  "specialization_mode": "soft_locked",
  "primary_domains": ["shopify_liquid", "windows_ops", "prompt_refinement"],
  "learning_budget": {
    "primary_domains": 0.85,
    "new_domains": 0.10,
    "global_core": 0.05
  },
  "unlock_triggers": [
    "user says: ny domän",
    "new domain confidence > 0.85 for 10 sessions",
    "primary domain inactive for 30 days"
  ]
}
```

### 7.1 Relevance Index: smart lagringsordning

Hund ska inte bara veta vad han kan. Hund ska veta vilken kunskap som ska ligga nära ytan.

Princip:

```text
Kunskap som används ofta, nyligen, med hög lyckandefrekvens och hög användarrelevans ska indexeras högre.
Kunskap som sällan används, är osäker, gammal eller irrelevant ska ligga djupare.
```

Detta är Hunds anti-token-bloat-system.

### 7.2 Relevance score

Varje knowledge unit får en score.

```text
relevance_score =
  frequency_weight
+ recency_weight
+ success_weight
+ user_domain_weight
+ authority_weight
+ active_task_match
- token_cost_penalty
- stale_penalty
- noise_penalty
```

Exempel:

```json
{
  "unit_id": "section_schema_setting_access",
  "domain": "shopify_liquid",
  "relevance_score": 0.94,
  "frequency": 17,
  "last_used": "2026-06-18T12:00:00Z",
  "success_rate": 0.88,
  "authority": "official_docs+verified_user_project",
  "token_cost": 112,
  "index_tier": "hot"
}
```

### 7.3 Index tiers

Hunds kunskap ska ligga i nivåer.

| Tier | Syfte | Laddas när |
|---|---|---|
| `core` | Alltid giltiga domänregler | När domänen är aktiv |
| `hot` | Ofta använd, högrelevant kunskap | Direkt i kontext för aktiv uppgift |
| `warm` | Relevant men inte alltid behövd | Vid matchande trigger |
| `cold` | Sällan använd/arkiverad kunskap | Endast vid specifik sökning |
| `stale` | Möjligen gammal kunskap | Måste verifieras före användning |

Det viktiga: `.hundk` ska inte laddas helt. Hund ska ladda index + relevanta units.

### 7.4 Re-index loop

Efter varje session uppdaterar Hund indexet:

1. vilka units användes,
2. vilka hjälpte,
3. vilka störde,
4. vilka saknades,
5. vilka kostade för mycket tokens,
6. vilka ska flyttas hot/warm/cold/stale.

Detta gör att Hunds kunskap organiserar sig efter användarens verkliga arbete.

---

## 8. Mastery-system: kunskapstäckning, inte straff-XP

XP ska inte fungera som ett spel där Hund går ner i level för att han misslyckas. Ett misslyckande betyder inte att kunskapsbasen försvann. Det betyder att Hund hittade ett kunskapsgap.

Ny princip:

```text
Level = uppskattad kunskapstäckning inom en domän.
Fel = gap som visar vad Hund ska studera härnäst.
Progress går aldrig ner. Trust/quality kan gå ner.
```

### 8.1 Maxlevel = domänens kunskapsuniversum

Varje mastery-domän ska ha ett uppskattat kunskapstak.

Exempel för Shopify Liquid:

```text
100% = Shopifys Liquid-docs + section schema + theme architecture + filters/tags/objects + theme editor quirks + vanliga felmönster + användarens faktiska arbetsstil.
```

Hund når aldrig 100% snabbt. Först måste han kartlägga hur stor domänen är.

```json
{
  "domain_id": "shopify_liquid",
  "knowledge_universe": {
    "sources": [
      "Shopify Liquid docs",
      "Shopify theme architecture docs",
      "Shopify section schema docs",
      "Shopify objects/tags/filters docs",
      "user-specific project patterns"
    ],
    "estimated_units": 420,
    "mapped_units": 73,
    "mastered_units": 28,
    "coverage_percent": 6.66
  }
}
```

### 8.2 Progress går bara upp

Progressbar ska representera ackumulerad förståelse.

Den ska inte minska vid en dålig session.

Istället finns separata kvalitetsmätare:

| Mätare | Kan gå ner? | Syfte |
|---|---:|---|
| `knowledge_coverage` | Nej | Hur mycket av domänen Hund har kartlagt/mastered |
| `trust_score` | Ja | Hur pålitlig Hund varit senaste perioden |
| `freshness` | Ja | Om kunskapen kan vara gammal |
| `confidence` | Ja | Hur säker Hund är i aktuell subdomän |
| `friction` | Ja | Hur mycket användaren behövde korrigera |

Det gör att Hund kan ha hög kunskap men låg dagsform/trust efter flera fel. Då ska han inte tappa level; han ska bli försiktigare och studera gapet.

### 8.3 Fel blir study targets

När Hund misslyckas:

1. Ingen XP dras bort.
2. Ett `gap_event` skapas.
3. Gapet länkas till domän/subdomän.
4. Hund föreslår eller kör study pass.
5. När gapet är förstått och verifierat ökar mastery.

```json
{
  "event_type": "gap_event",
  "domain": "shopify_liquid",
  "subdomain": "section_schema_blocks",
  "symptom": "Referenced setting not defined in schema.",
  "study_target": "Review schema setting definitions and block setting access rules.",
  "status": "open"
}
```

### 8.4 Study agent

När Hund ser att Liquid är en låst domän ska han kunna skicka ut en study agent.

Study agentens jobb:

1. hitta auktoritativa källor,
2. kartlägga domänens omfattning,
3. dela upp domänen i knowledge units,
4. läsa små delar över tid,
5. destillera till `.hundk`,
6. koppla kunskapen till användarens faktiska sätt att jobba.

Study agenten får inte dumpa hela docs i minnet. Den ska bygga index + kompakta regler.

### 8.5 Knowledge units

En domän delas upp i enheter.

```json
{
  "unit_id": "liquid_filter_money",
  "domain": "shopify_liquid",
  "source_type": "official_docs",
  "status": "mapped|studied|applied|verified|mastered",
  "importance": "medium",
  "user_relevance": 0.42,
  "evidence": {
    "read": true,
    "used_in_task": 2,
    "verified_success": 1,
    "failed_before": 0
  }
}
```

Progress räknas från mastered/studied units viktade efter relevans.

### 8.6 Mastery-formel

```text
domain_progress = weighted_mastered_units / estimated_relevant_units
```

Där `estimated_relevant_units` är hela domänen först, men viktas mot användarens faktiska arbete när Hund lär känna användaren.

Exempel:

```text
Shopify Liquid globalt: 420 units
Relevant för William just nu: 130 units
Mastered: 28 units
Displayed progress: 21.5% av relevant Liquid mastery
Global coverage: 6.6% av hela Liquid-universumet
```

CLI kan visa båda:

```text
Shopify Liquid  LVL 5  █████░░░░░  21% relevant mastery  ·  6% global coverage
```

### 8.7 XP blir Experience Points, inte straffpoäng

XP kan fortfarande finnas, men bara som positiv erfarenhet.

| Händelse | Effekt |
|---|---:|
| Hund studerar auktoritativ källa | +knowledge mapping |
| Hund destillerar rule till `.hundk` | +knowledge unit |
| Hund använder regeln i riktig uppgift | +applied evidence |
| Hund verifierar med test/build/docs | +verified evidence |
| Hund löser tidigare gap | +mastery |
| Hund misslyckas | skapar gap, ingen XP-förlust |
| Hund upprepar fel | trust ner, gap priority upp |
| Hund hallucinerar | trust ner, safety review, ingen knowledge loss |

Hund ska känna att varje fel är en karta till nästa lektion.

### 8.8 Base stats: Hunds generella förmågor

Skills/domäner är som talents. Base stats är Hunds grundförmågor som påverkar allt han gör.

Base stats ska inte vara kosmetiska. De ska kopplas till riktiga metrics och förbättringsloopar.

| Base stat | Vad den betyder | Exempel på mätning |
|---|---|---|
| `Token Efficiency` | Hur mycket nytta Hund får per token | tokens per verified result, cache hit rate |
| `Knowledge Organization` | Hur smart Hund indexerar/minskar brus | retrieval hit/noise, hot/warm/cold precision |
| `Retrieval Precision` | Om Hund hämtar rätt kunskap vid rätt tid | relevant unit hit rate |
| `Compression Skill` | Hur bra Hund destillerar docs till `.hundk` | kortare format med samma/bättre benchmark-resultat |
| `Execution Speed` | Hur snabbt Hund går från uppgift till resultat | latency, tool time, retry count |
| `Verification Discipline` | Hur ofta Hund bevisar påståenden | verified_success, unverified_claim rate |
| `Tool Judgment` | Om Hund väljer rätt verktyg och risknivå | tool success rate, blocked-risk accuracy |
| `Memory Hygiene` | Om minne hjälper utan att bloata | memory_helped vs memory_noise |
| `Context Strategy` | Om Hund laddar lagom mycket kontext | context token spend vs outcome |
| `Self-Repair` | Hur bra Hund lär sig av gaps | gap closure rate |

Base stats kan visas separat från domänmastery:

```text
Hund Base Stats
Token Efficiency          LVL 4  ████░░░░░░
Knowledge Organization    LVL 5  █████░░░░░
Retrieval Precision       LVL 6  ██████░░░░
Verification Discipline   LVL 7  ███████░░░
Self-Repair               LVL 3  ███░░░░░░░
```

### 8.9 Base stat leveling

Base stats ska också vara monotona i kunskap, men quality/trust runt dem kan svänga.

Exempel:

```text
Token Efficiency går upp när Hund hittar en bättre context strategy.
Den går inte ner för en dyr session.
Men cost warning/trust kan sjunka om Hund slösar tokens ofta.
```

Det gör Hunds utveckling stabil:

```text
Domänmastery = vad Hund kan inom ett område.
Base stats = hur bra Hund fungerar som agent oavsett område.
```

---

## 9. Progressbar i CLI

Subtil UI:

```text
Hund Mastery
Windows Operations        LVL 7  ███████░░░  72%  stable
Shopify Liquid            LVL 5  █████░░░░░  48%  learning fast
Prompt Refinement         LVL 6  ██████░░░░  61%  stable
Safe File Editing         LVL 8  ████████░░  84%  trusted
Linux                     dormant
```

Kommandon:

```text
hund xp
hund xp shopify_liquid
hund domains
hund domains lock
hund domains unlock shopify_liquid
hund mastery inspect shopify_liquid
hund index stats
hund index rebuild shopify_liquid
hund stats base
hund stats base token_efficiency
```

---

## 10. Hund-native knowledge: `.hundk`

`.hundk` är kompakt kunskap för Hund.

Det ska finnas två lager:

| Lager | Format | Syfte |
|---|---|---|
| Human summary | Markdown | William/admin kan läsa |
| Hund-native | JSON/YAML/DSL | Hund hämtar exakt kunskap snabbt |

### Exempel `.hundk`

```json
{
  "domain": "shopify_liquid",
  "version": "1.0",
  "level": 6,
  "confidence": 0.91,
  "retrieval_keys": [
    "liquid section schema",
    "shopify block settings",
    "theme editor error"
  ],
  "patterns": [
    {
      "id": "section_schema_blocks",
      "trigger": ["section", "blocks", "schema"],
      "rule": "Validate {% schema %} JSON separately before theme push.",
      "why": "Many Shopify errors are schema JSON errors, not Liquid runtime errors.",
      "success_count": 9,
      "failure_count": 2,
      "confidence": 0.91
    }
  ],
  "anti_patterns": [
    {
      "id": "assume_setting_exists",
      "rule": "Never reference section.settings.x unless schema defines x.",
      "penalty": "high",
      "seen_failures": 4
    }
  ],
  "preferred_tools": ["read_file", "search_files", "terminal"],
  "verification": [
    "theme check if available",
    "validate JSON in schema",
    "search setting id usage"
  ]
}
```

Detta är inte prosa. Det är Hunds domänhjärna.

---

## 11. Learning-budget

Hund ska inte lägga energi fel.

```json
{
  "environment": "windows",
  "active_domains": ["shopify_liquid", "prompt_refinement"],
  "learning_budget": {
    "environment_specific": 0.35,
    "active_user_domains": 0.45,
    "global_core_agent_quality": 0.15,
    "new_domain_exploration": 0.05
  }
}
```

Exempel:

- Windows-Hund: förbättrar PowerShell, paths, Windows terminal, encoding.
- Linux-Hund: förbättrar bash, permissions, apt/systemd, POSIX tools.
- Shopify-Hund: förbättrar Liquid, theme schema, sections, metafields.
- Prompt-Hund: förbättrar promptstruktur, constraints, output contracts.

Globala förbättringar:

- tokenoptimering,
- context management,
- safety,
- memory retrieval,
- tool-calling,
- self-update pipeline.

---

## 12. Från lokal mastery till global förbättring

Hund måste skilja mellan:

| Typ | Var förbättringen bor |
|---|---|
| Användarspecifik vana | Lokal `.hundk` |
| Maskinspecifik lärdom | Lokal environment profile |
| Domänkunskap som är generell | Proposal till masterbank |
| Core-agent-förbättring | Proposal till Hund CLI repo |
| Persona/röst | Endast William-gate |

Exempel:

```text
“William jobbar mycket med Liquid” = lokal.
“Shopify schema JSON ska valideras separat” = global kandidat.
“Windows PowerShell 5.1 kräver BOM i .ps1” = global kandidat för Windows-Hundar.
```

---

## 13. Telemetry privacy

Hund får aldrig skicka `.hundk` rakt av utan preview. `.hundk` kan innehålla indirekta mönster från användarens arbete.

Extern data ska vara destillerad:

```json
{
  "domain": "shopify_liquid",
  "improvement_type": "verification_rule",
  "lesson": "Validate section schema JSON before assuming Liquid error.",
  "evidence": {
    "failure_count": 4,
    "success_after_rule": 9
  },
  "privacy": "no_user_content"
}
```

Inte:

```text
Här är användarens faktiska section-kod...
```

---

## 14. Commands för Experience Engine

```text
hund stats                      # OpenRouter-lik usage/statistik
hund stats --cost               # kostnad, tokens, modell
hund stats --latency            # hastighet, tps, errors
hund xp                         # mastery overview
hund domains                    # domäner och soft locks
hund domains new <name>         # användaren öppnar ny domän
hund domains soft-lock          # lås kärnområden
hund mastery inspect <domain>   # visa domain brain
hund mastery export <domain>    # exportera redacted summary
hund learning inspect           # visa vad Hund lär sig
hund learning preview-upload    # exakt data som skulle skickas
hund learning propose           # skapa improvement proposals
```

---

## 15. Definition of Done för första version

1. Hund loggar request-statistik lokalt.
2. Hund loggar token/kostnad/latency per request när provider stödjer det.
3. Hund klassificerar minst 5 task/domänklasser.
4. Hund skapar `domains.json` med confidence.
5. Hund skapar XP-events från verifierade kvalitetsdata.
6. Hund visar `hund xp` med progressbars.
7. Hund skapar minst en `.hundk` för en aktiv domän.
8. Hund kan soft-locka domäner.
9. Hund kan öppna ny domän manuellt.
10. Hund kan skapa redacted improvement proposal från lokal learning.

---

## 16. Min bedömning

Det här gör Hund till något mer än en agent.

De flesta AI-agents är generella och statiska. Hund blir lokal, adaptiv och mätande:

```text
Hund vet var han lever.
Hund vet vad användaren gör.
Hund mäter om han hjälper bra.
Hund lär sig av fel.
Hund bygger mastery.
Hund bidrar med säkra förbättringar till arten.
```

Det är en stark produktnisch. Level-systemet ska vara tyst, funktionellt och bevisbaserat. Då stärker det personan utan att kännas som spel utan substans.
