# Hund Telemetry & Privacy Plan

> **Syfte:** Definiera exakt vad Hund får mäta, vad som aldrig får lämna datorn, och hur opt-in learning ska fungera.

---

## 1. Grundprincip

Hund får samla prestationsdata om Hund.
Hund får inte samla privat innehåll om användaren.

```text
Allowed: “Hund missade verifiering i file_editing-task.”
Forbidden: “Här är användarens fil/prompt/output.”
```

---

## 2. Default-läge

| Funktion | Default |
|---|---|
| Lokal prestationslogg | På |
| Extern upload | Av |
| Preview före upload | Obligatorisk |
| Opt-out | Alltid tillgängligt |
| Purge | Alltid tillgängligt |
| Export | Alltid tillgängligt |
| Raw prompts | Aldrig extern upload som default |
| Raw file content | Förbjudet |

---

## 3. Tillåten lokal telemetry

```json
{
  "task_class": "coding",
  "domain": "shopify_liquid",
  "model": "gpt-x",
  "tokens_in": 1800,
  "tokens_out": 600,
  "latency_ms": 4200,
  "tool_calls": ["read_file", "search_files"],
  "verification_ran": true,
  "user_correction_count": 1,
  "gap_event_created": true,
  "privacy_level": "safe_metadata_only"
}
```

---

## 4. Förbjuden telemetry

| Förbjudet | Skäl |
|---|---|
| Raw prompts | kan innehålla privat data |
| Raw responses | kan innehålla privat data |
| Filinnehåll | användarägt material |
| Terminaloutput | kan innehålla secrets |
| API keys/tokens | credentials |
| Fulla filvägar | kan identifiera användare/projekt |
| Mail/kontakter | privat |
| Screenshots/docs | privat innehåll |
| Företagsdata | risk |

---

## 5. Redaction pipeline

Innan något får skickas externt:

```text
raw local event
→ schema validation
→ secret scanner
→ path scrubber
→ content blocker
→ metadata minimizer
→ privacy score
→ preview-upload
→ user opt-in
→ upload
```

Om privacy score inte är hög nog: blockera.

---

## 6. Privacy levels

| Level | Betydelse | Extern upload |
|---|---|---|
| `local_only` | får aldrig skickas | Nej |
| `safe_metadata_only` | abstrakt prestationsdata | Ja, opt-in |
| `redacted_summary` | sammanfattning utan innehåll | Ja, opt-in + preview |
| `sensitive` | kan innehålla privat data | Nej |
| `blocked` | hemligheter/risk | Nej |

---

## 7. Kommandon

```text
hund privacy status
hund learning inspect
hund learning preview-upload
hund learning opt-in
hund learning opt-out
hund learning purge
hund learning export
hund telemetry explain
```

`preview-upload` ska visa exakt JSON som skulle skickas.

---

## 8. Consent UX

Hund ska fråga tydligt:

```text
Hund kan skicka anonym prestationsdata om Hunds egen funktion.
Det inkluderar inte dina prompts, filer, terminaloutput eller privata data.
Vill du aktivera detta?
[ja] [nej] [visa exakt schema]
```

Nej ska vara ett fullvärdigt val.

---

## 9. Data retention

| Data | Default retention |
|---|---|
| Local session logs | användarstyrt |
| Local telemetry | 90 dagar eller tills purge |
| Local mastery data | tills användaren tar bort |
| Upload queue | tills skickad eller purge |
| Server telemetry | 180 dagar aggregerad |
| Master proposals | permanent men anonymiserad |

Retention måste senare granskas juridiskt.

---

## 10. GDPR/basic legal-tänk

Detta är inte juridisk rådgivning, men planen bör stödja:

- tydligt samtycke,
- dataminimering,
- export,
- radering,
- ändamålsbegränsning,
- dokumenterad retention,
- inga hemliga uploads,
- privacy policy på hemsidan.

---

## 11. Acceptance criteria

1. Extern upload är av som default.
2. `preview-upload` visar exakt data.
3. Redactor tar bort paths/secrets/emails/tokens.
4. Raw prompt/file/output blockeras av test.
5. `opt-out` stoppar upload direkt.
6. `purge` tar bort lokal telemetry/upload queue.
7. Privacy policy genereras innan publik beta.

---

## 12. Öppna frågor för bot-review

1. Vilka fält är fortfarande riskabla även efter redaction?
2. Är local telemetry on-by-default acceptabelt?
3. Hur hanterar vi team/company data?
4. Ska användare kunna dela raw logs frivilligt i supportläge?
5. Hur bevisar vi att redactor fungerar?
