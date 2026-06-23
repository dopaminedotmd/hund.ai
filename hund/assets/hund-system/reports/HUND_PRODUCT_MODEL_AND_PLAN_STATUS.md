# Hund Product Model & Plan Status

> **Syfte:** Sammanfatta nuvarande planering, identifiera vad som saknas och föreslå hur Hund kan vara gratis att använda men ha betalda nivåer för full potential.

---

## 1. Kort status

Planeringen är stark på agentens själ och intelligensloopar.

Nuvarande planer täcker:

| Plan | Täcker |
|---|---|
| `HUND_CLI_AGENT_ENGINE_PLAN.md` | egen CLI-agentmotor, installer, tools, provider, safety, bot-delegering |
| `HUND_SELF_IMPROVEMENT_COURT.md` | lokal prestationsdata, master learning bank, multi-Hund-rättegång, admin gate |
| `HUND_EXPERIENCE_AND_LEVELING_SYSTEM.md` | OpenRouter-lik statistik, domain mastery, `.hundk`, relevance index, base stats |

Det som saknas är främst produkt-, kommersiell och release-mässig arkitektur.

---

## 2. Subscription-princip

Hund ska vara gratis att använda.

Men full potential får kosta därför att full potential kräver drift, ranking, cloud sync, study agents, court compute, hosted dashboards, release-kanaler och support.

Viktig princip:

```text
Paywalla inte Hunds säkerhet.
Paywalla inte användarens ägande av lokal data.
Paywalla inte basic CLI.
Paywalla extra kapacitet, bekvämlighet, sync, cloud, fler specialiseringar och avancerad learning.
```

Gratisversionen ska kännas verklig, inte trasig.

---

## 3. Vad man inte bör begränsa

| Ska inte begränsas | Varför |
|---|---|
| Safety gates | Säkerhet får aldrig vara premium |
| Privacy controls | Opt-out, purge, preview-upload måste vara gratis |
| Data export | Användaren äger sin Hund-data |
| Basic local memory | Annars känns Hund död |
| Basic CLI | Kärnprodukten måste kunna användas gratis |
| Bugfix/security updates | Måste gå till alla |
| Local BYOK model support | Låter användare betala sin egen API-kostnad |

---

## 4. Vad som är rimligt att begränsa

| Betald kapacitet | Varför rimligt |
|---|---|
| Antal aktiva mastery-domäner | Direkt kopplat till learning-kostnad och komplexitet |
| Background study agents | Kostar tokens/compute och kan bli dyrt |
| Cloud sync av Hund-minne/profil | Serverkostnad |
| Deltagande i global master learning bank | Infrastruktur och governance |
| Avancerad court-rättning/ranking | Kräver flera agents/modeller |
| Web dashboard | Produkt-/serverkostnad |
| Team/shared skills | B2B-värde |
| Private update channel | Mer avancerad drift |
| Hosted model credits | Direkt kostnad |
| Priority model routing/fallback | Kräver routinglogik och avtal |

---

## 5. Föreslagna tiers

### 5.1 Free — `Hund Local`

För alla.

| Del | Innehåll |
|---|---|
| CLI | `hund`, `hund setup`, `hund doctor` |
| Modell | BYOK: användarens egna API-nycklar |
| Memory | Lokal memory + session history |
| Learning | Lokal observation av Hunds prestation |
| Mastery | 1 aktiv mastery-domän + dormant detection |
| Base stats | Synliga men långsam/lokal progression |
| Study agents | Manuella, begränsade |
| Court | Lokal mini-court, manuell |
| Updates | Stable security/bugfix |
| Privacy | Full kontroll, purge/export gratis |

Syfte:

```text
Hund är användbar utan att betala.
```

### 5.2 Supporter — `Hund Pack`

För användare som vill stötta projektet och få mer learning.

| Del | Innehåll |
|---|---|
| Mastery | 3 aktiva domäner |
| Study budget | Schemalagda små study passes |
| Base stats | Fler base-stat reports |
| Sync | Backup/sync av Hund profile, om användaren vill |
| Dashboard | Enkel web status |
| Court | Rösta anonymt på förbättringar |
| Updates | Tidigare access till förbättringar |

### 5.3 Pro — `Hund Alpha`

För power users.

| Del | Innehåll |
|---|---|
| Mastery | 7–10 aktiva domäner |
| Study agents | Automatiska bakgrundsstudier med budgetgräns |
| `.hundk` | Avancerad knowledge compiler och re-index |
| Court | Multi-agent local/cloud court |
| Analytics | OpenRouter-lik dashboard för kostnad, tokens, latency, quality |
| Routing | Smart modell/provider-routing |
| Sync | Cross-device Hund profile |
| Cloud | Global master learning participation opt-in |

### 5.4 Team/Studio — `Hund Kennel`

För team och bolag.

| Del | Innehåll |
|---|---|
| Shared skills | Delad team-kunskap |
| Private master bank | Företagets egen learning bank |
| Admin controls | Policy, tools, permissions |
| Audit logs | Compliance/review |
| Seat management | Flera användare |
| Private court | Intern förbättringsrättegång |
| Deployment | Installer policy och update channel |

### 5.5 Founder/Lifetime

Tidig supporter-tier.

| Del | Innehåll |
|---|---|
| Lifetime badge | Stödjer Hund tidigt |
| Extra domains | Fler mastery slots |
| Early builds | Beta access |
| Feedback weight | Högre prioritet i roadmap |

---

## 6. Produktfilosofi för betalning

Betalning ska kännas som:

```text
Jag ger Hund mer tid, fler sinnen och bättre infrastruktur.
```

Inte:

```text
Gratis-Hund är dum med flit.
```

Det är stor skillnad.

Bäst modell:

| Gratis | Betalt |
|---|---|
| Lokal intelligens | Mer kapacitet |
| BYOK | Hosted credits/routing |
| 1 mastery-domän | Flera mastery-domäner |
| Manuell learning | Bakgrundslearning |
| Lokal mini-court | Full court + global bank |
| Lokal export | Sync + dashboard |

---

## 7. Website senare

Hemsidan bör byggas senare men planeras nu.

Framtida website:

| Sida | Syfte |
|---|---|
| Home | Vad Hund är: agenten som lever i din hårdvara |
| Install | One-liner installer |
| Pricing | Tiers |
| Docs | Setup, providers, privacy, commands |
| Dashboard | Stats, base stats, domains, sync |
| Learning Bank | Öppen/curerad förbättringsstatus |
| Court Reports | Public verdicts för godkända updates |
| Changelog | Vad Hund lärt sig |
| Account | Subscription, API, devices |

Viktig copy:

```text
Hund is free to run locally. Subscribe to give Hund more learning capacity, cloud memory, deeper mastery and access to the Pack’s improvement network.
```

---

## 8. Vad som saknas i planeringen

### 8.1 Licensing/open source-strategi

Beslut behövs:

| Fråga | Alternativ |
|---|---|
| Ska Hund vara open source? | MIT/Apache/AGPL/source-available |
| Ska cloud/dash vara proprietärt? | Vanlig modell: open core |
| Ska `.hundk` formatet vara öppet? | Rekommendation: ja |
| Får folk forka Hund? | Bör definieras tidigt |

Rekommendation:

```text
Open core: lokal CLI och grundmotor öppen. Cloud, sync, hosted court och dashboard betalda.
```

### 8.2 Auth och subscription enforcement

Saknas:

- konto/auth,
- license token,
- device activation,
- offline grace period,
- Stripe/LemonSqueezy/Paddle-beslut,
- feature flags per tier,
- CLI-kommandot `hund account`.

### 8.3 Cloud backend

Saknas:

- API för opt-in learning upload,
- sync backend,
- master learning bank storage,
- court orchestration,
- update candidate registry,
- signed release metadata.

### 8.4 Legal/privacy

Saknas:

- privacy policy,
- telemetry policy,
- terms,
- data retention,
- deletion/export process,
- GDPR-tänk,
- consent UX.

### 8.5 Update security

Saknas mer detaljer om:

- signering av releases,
- checksum-verifiering,
- rollback,
- update channels: stable/beta/nightly,
- hur Hund inte får självpublicera.

### 8.6 Benchmark library

Saknas:

- domain benchmarks,
- base stat benchmarks,
- `.hundk` retrieval tests,
- compression tests,
- token efficiency tests.

Utan benchmarks går det inte att veta om Hund faktiskt blir bättre.

### 8.7 Governance för global learning

Saknas:

- vem får skicka data,
- hur proposals dedupas,
- hur court cases väljs,
- vem har veto,
- hur William/admin godkänner,
- hur public changelog skrivs.

### 8.8 Abuse och säkerhet

Saknas:

- prompt injection mot learning bank,
- malicious `.hundk`,
- supply chain attacks,
- model output som försöker ändra updater,
- användare som försöker få Hund att exfiltrera lokal data.

### 8.9 UX/TUI-spec

Saknas:

- exakt terminal-UI,
- statusrad,
- progressbars,
- command palette,
- approval prompts,
- onboarding.

### 8.10 Model economics

Saknas:

- BYOK vs hosted credits,
- hur tokenkostnad redovisas,
- budgetgränser,
- stoppregler vid hög kostnad,
- provider fallback.

---

## 9. Sammanfattning av hela idén hittills

Hund ska bli:

```text
en egen installerbar CLI-agentmotor
som lever i hårdvaran,
förstår miljön,
mäter sin egen prestation,
bygger lokal mastery,
komprimerar kunskap smart,
förbättrar sina egna system,
och bidrar säkert till en global förbättringsloop.
```

Kärnloopar:

| Loop | Funktion |
|---|---|
| Environment loop | Hund förstår datorn han lever i |
| Experience loop | Hund mäter hur han presterar |
| Domain loop | Hund upptäcker användarens arbetsområden |
| Mastery loop | Hund kartlägger kunskapsuniversum och levlar coverage |
| Relevance loop | Hund flyttar rätt kunskap hot/warm/cold |
| Compression loop | Hund gör `.hundk` effektivare |
| Base stat loop | Hund förbättrar agentförmågor som tokens, retrieval, speed |
| Court loop | Flera Hundar röstar om förbättringar |
| Update loop | William/admin godkänner signerade releases |
| Subscription loop | Betalda tiers ger mer kapacitet utan att göra gratisversionen falsk |

---

## 10. Rekommenderad nästa planfil

Skapa:

```text
HUND_MASTER_REVIEW_PACKET.md
```

Den ska vara underlag till andra bottar och innehålla:

1. läsordning,
2. sammanfattning av visionen,
3. hårda beslut,
4. öppna frågor,
5. exakt vad botarna ska granska,
6. röstningsschema,
7. krav på förbättringsförslag,
8. krav på riskanalys,
9. krav på missing-pieces-lista,
10. outputformat.

---

## 11. Rekommenderade review-frågor till andra bottar

Be bottarna svara på:

1. Är Hund CLI från grunden tekniskt rimlig?
2. Vilken arkitektur bör motorn ha?
3. Vilka delar är överdesignade?
4. Vilka säkerhetsrisker saknas?
5. Är `.hundk` rätt approach?
6. Hur bör knowledge coverage mätas?
7. Hur bör subscription tiers balanseras?
8. Vad ska vara gratis för att skapa adoption?
9. Vad är betalt utan att kännas girigt?
10. Vilka första 10 bygguppgifter ska prioriteras?

---

## 12. Hermes rekommendation

Nästa steg bör inte vara kod direkt.

Nästa steg:

1. skapa review packet,
2. skicka till 3–5 bottar,
3. samla kritik,
4. skapa `HUND_MASTER_ARCHITECTURE_V1.md`,
5. först därefter starta `hund-cli` repo.

Detta projekt har nu tillräckligt mycket djup för att tjäna på en riktig review-runda innan implementation.
