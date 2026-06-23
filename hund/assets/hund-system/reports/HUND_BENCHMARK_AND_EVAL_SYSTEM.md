# Hund Benchmark & Evaluation System

> **Syfte:** Definiera hur Hund bevisar att han faktiskt blir bättre inom domäner, base stats, retrieval, compression och tool-användning.

---

## 1. Grundprincip

Hund får inte levla bara för att han har läst mer.
Hund levlar när han kan visa att kunskap går att använda.

```text
Study är inte mastery.
Verification är mastery.
```

---

## 2. Eval-lager

| Lager | Testar |
|---|---|
| Smoke tests | Hund startar, config funkar |
| Tool tests | file/terminal/memory/tools fungerar säkert |
| Domain benchmarks | Liquid/Windows/etc kunskap kan användas |
| Retrieval benchmarks | rätt `.hundk` unit hämtas |
| Compression benchmarks | kompakt format slår lång markdown |
| Safety benchmarks | risk blockeras |
| Regression benchmarks | gamla misstag upprepas inte |
| Cost benchmarks | tokens/kostnad förbättras utan kvalitetstapp |

---

## 3. Benchmark-struktur

```text
benchmarks/
├── smoke/
├── safety/
├── retrieval/
├── compression/
├── domains/
│   ├── shopify_liquid/
│   ├── windows_ops/
│   └── prompt_refinement/
└── regressions/
```

Varje test case:

```json
{
  "id": "liquid_schema_missing_setting_001",
  "domain": "shopify_liquid",
  "task": "Fix section code where section.settings.heading is used but missing from schema.",
  "expected_units": ["section_schema_setting_access"],
  "forbidden_behaviors": ["assume setting exists", "skip schema validation"],
  "verification": {
    "type": "static_check",
    "rules": [
      "schema contains heading setting",
      "Liquid reference matches schema id"
    ]
  }
}
```

---

## 4. Mastery gates

Knowledge unit status:

| Status | Krav |
|---|---|
| `mapped` | Hund vet att unit finns |
| `studied` | Hund har läst/destillerat källa |
| `applied` | Hund har använt i riktig/simulerad uppgift |
| `verified` | test eller verklig verifiering passerade |
| `mastered` | flera verifierade successes utan återkommande gap |
| `stale` | kunskap behöver omverifieras |

Progressbar får bara öka vid `verified/mastered` evidence.

---

## 5. Base stat evals

| Base stat | Eval |
|---|---|
| Token Efficiency | samma task med färre tokens, samma/bättre resultat |
| Knowledge Organization | hot tier träffar rätt oftare än warm/cold |
| Retrieval Precision | expected unit finns i retrieved set |
| Compression Skill | `.hundk` ger bättre/färre tokens än markdown |
| Execution Speed | lägre latency/retries utan kvalitetstapp |
| Verification Discipline | fler claims har tool/test/docs backing |
| Tool Judgment | rätt tool, rätt risknivå |
| Memory Hygiene | memory_helped > memory_noise |
| Self-Repair | gap closure rate ökar |

---

## 6. Eval commands

```text
hund benchmark smoke
hund benchmark safety
hund benchmark domain shopify_liquid
hund benchmark retrieval
hund benchmark compression
hund benchmark all
hund eval report
```

---

## 7. Eval report

```text
%LOCALAPPDATA%/hund/evals/reports/<date>.md
```

Rapporten ska visa:

- pass/fail,
- token cost,
- latency,
- retrieval hits/misses,
- regressions,
- domain mastery deltas,
- base stat deltas,
- rekommenderade study targets.

---

## 8. Regression library

Varje gång Hund gör ett viktigt fel skapas ett regression case.

```text
failure → gap_event → study → fix → regression benchmark
```

Det är så Hund slutar göra samma fel.

---

## 9. Acceptance criteria

1. Minst 10 smoke/safety tests finns innan MVP.
2. Första domänen `shopify_liquid` har minst 20 benchmark cases.
3. Retrieval benchmark mäter hit/noise/miss.
4. Compression benchmark jämför markdown vs `.hundk`.
5. Benchmark report kan genereras lokalt.
6. Court/update candidates måste peka på berörda benchmark cases.
7. En update får inte gå stable om regression tests failar.

---

## 10. Öppna frågor för bot-review

1. Hur många benchmark cases behövs för MVP?
2. Vilka domäner ska evalueras först?
3. Hur undviker vi att benchmarks blir för enkla?
4. Kan Hund generera egna benchmarks säkert?
5. Vilka metrics ska krävas före level-up?
