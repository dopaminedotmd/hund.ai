# Hund Master Review Packet

> **Syfte:** Detta är paketet som ska skickas till andra bottar för grundlig granskning innan `hund-cli` börjar byggas.

---

## 1. Läsordning för reviewer-bot

Läs dessa filer i ordning:

1. `reports/HUND_CLI_AGENT_ENGINE_PLAN.md`
2. `reports/HUND_SELF_IMPROVEMENT_COURT.md`
3. `reports/HUND_EXPERIENCE_AND_LEVELING_SYSTEM.md`
4. `reports/HUND_PRODUCT_MODEL_AND_PLAN_STATUS.md`
5. `reports/HUND_SECURITY_UPDATE_ROLLBACK.md`
6. `reports/HUND_TELEMETRY_PRIVACY_POLICY.md`
7. `reports/HUND_BENCHMARK_AND_EVAL_SYSTEM.md`
8. `reports/HUND_SUBSCRIPTION_AND_WEBSITE_SPEC.md`

---

## 2. Vision i en mening

Hund är en egen installerbar CLI-agentmotor som lever i användarens hårdvara, förstår sin miljö, mäter sin egen prestation, bygger lokal mastery, förbättrar sina egna system säkert och kan bidra anonymt till en global förbättringsloop.

---

## 3. Hårda beslut hittills

| Beslut | Status |
|---|---|
| Bygga egen agentmotor, inte bara wrapper | Preliminärt ja |
| Hund ska ha egen CLI: `hund` | Ja |
| Hund ska analysera hårdvara/miljö vid uppstart | Ja |
| Persona ska inte ändras | Ja |
| Local-first | Ja |
| Extern telemetry opt-in | Ja |
| Raw user data får inte uploadas | Ja |
| Self-improvement via court, inte auto-publicering | Ja |
| Progress ska inte gå ner vid misslyckande | Ja |
| Misslyckanden blir gap events | Ja |
| Skills/domäner + base stats | Ja |
| Subscription ska ge kapacitet, inte säkerhet | Ja |

---

## 4. Saker reviewer ska leta efter

1. Överdesign.
2. Saknade säkerhetsrisker.
3. Felaktiga antaganden om agentmotorer.
4. Privacy-läckor.
5. Subscription som känns fel/girig.
6. Orealistiska MVP-krav.
7. Bättre arkitektur för `.hundk`.
8. Bättre eval/benchmark-modell.
9. Bättre update/rollback-modell.
10. Första byggbara task-listan.

---

## 5. Review-outputformat

Reviewer-bot ska svara exakt med dessa sektioner:

```text
# REVIEW: Hund CLI

## 1. Kort dom
GO / NO-GO / GO WITH CHANGES

## 2. Största styrkor
- ...

## 3. Största risker
- ...

## 4. Vad är överdesignat?
- ...

## 5. Vad saknas?
- ...

## 6. Säkerhet/privacy
- ...

## 7. Tekniskt arkitekturförslag
- ...

## 8. MVP-förslag
- ...

## 9. Subscription-feedback
- ...

## 10. Första 10 bygguppgifter
1. ...

## 11. Frågor till William
- ...
```

---

## 6. Röstning

Reviewer ska sätta score 1–10:

| Score | Fråga |
|---|---|
| Vision clarity | Är visionen tydlig? |
| Technical feasibility | Går det bygga? |
| MVP realism | Är första version realistisk? |
| Safety | Är säkerheten tillräcklig? |
| Privacy | Är privacy-modellen tillräcklig? |
| Product value | Är produkten stark? |
| Monetization | Är tiers rimliga? |
| Differentiation | Är Hund unik? |
| Implementation readiness | Kan kodning börja snart? |
| Risk level | Hur farligt/svårt är projektet? |

---

## 7. Reviewer-instruktion prompt

```text
Du ska granska planeringen för Hund CLI, en egen installerbar self-improving CLI-agentmotor.

Läs alla filer i läsordningen. Var kritisk. Leta efter saknade säkerhetslager, överdesign, tekniska risker, MVP-problem, privacy-risker och produktluckor.

Du ska inte koda. Du ska ge en grundlig review enligt outputformatet i HUND_MASTER_REVIEW_PACKET.md.

Viktigt:
- Föreslå konkretare arkitektur där planen är vag.
- Säg vad som bör tas bort eller skjutas upp.
- Säg vad som måste byggas först.
- Säg vilka delar som är farliga eller orealistiska.
- Bedöm subscriptionmodellen utan att göra Hund girig.
- Bevara Hunds persona och kärnvision.
```

---

## 8. Förväntad nästa process

1. Skicka packet till 3–5 bottar.
2. Samla reviews.
3. Hermes sammanfattar reviews.
4. Skapa `HUND_MASTER_ARCHITECTURE_V1.md`.
5. Skapa `HUND_MVP_BUILD_PLAN.md`.
6. Starta nytt repo: `C:\Users\willi\Desktop\hund-cli`.

---

## 9. Review-bottar

Rekommenderade roller:

| Bot | Roll |
|---|---|
| Antigravity | övergripande produkt/arkitektur |
| Claude Code | implementation realism |
| Gemini | research/säkerhet/marknad |
| OpenCode | CLI/TUI och kodstruktur |
| Hermes | second review och sammanfogning |

---

## 10. Viktigaste fråga

```text
Vad är minsta versionen av Hund som fortfarande bevisar visionen?
```

Det är den fråga review-rundan ska svara på.
