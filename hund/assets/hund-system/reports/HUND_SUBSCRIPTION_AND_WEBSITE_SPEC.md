# Hund Subscription & Website Spec

> **Syfte:** Definiera hur Hund kan vara gratis att använda men ha betalda nivåer som låser upp mer kapacitet, sync, court, study agents och dashboard utan att kännas girigt.

---

## 1. Produktprincip

```text
Free Hund = riktig lokal agent.
Paid Hund = mer kapacitet, mer learning, mer sync, mer infrastruktur.
```

Paywalla inte säkerhet, privacy, export eller basic local use.

---

## 2. Tiers

| Tier | Målgrupp | Kärna |
|---|---|---|
| Hund Local | alla | gratis lokal CLI |
| Hund Pack | supporters | mer mastery + sync + dashboard light |
| Hund Alpha | pro users | full learning/court/analytics |
| Hund Kennel | team | shared skills/private learning bank |
| Founder | tidiga supporters | lifetime/early access |

---

## 3. Feature matrix

| Feature | Local | Pack | Alpha | Kennel |
|---|---:|---:|---:|---:|
| CLI `hund` | Ja | Ja | Ja | Ja |
| BYOK models | Ja | Ja | Ja | Ja |
| Basic local memory | Ja | Ja | Ja | Ja |
| Active mastery domains | 1 | 3 | 7-10 | policy |
| Base stats | basic | full | full | full |
| Background study agents | manuell | låg budget | hög budget | policy |
| `.hundk` compiler | basic | improved | advanced | shared/private |
| Cloud sync | Nej | Ja | Ja | Ja |
| Dashboard | Nej | light | full | admin |
| Global learning bank | preview only | opt-in vote | opt-in full | private/global options |
| Multi-agent court | local mini | limited | full | private court |
| Hosted credits | Nej | addon | addon/included | contract |
| Team policy | Nej | Nej | Nej | Ja |

---

## 4. CLI account commands

```text
hund account login
hund account logout
hund account status
hund subscription status
hund subscription upgrade
hund subscription sync-license
hund subscription explain-limits
```

Hund ska fungera offline med grace period om license redan är verifierad.

---

## 5. Feature flags

```json
{
  "tier": "alpha",
  "features": {
    "active_mastery_domains": 10,
    "cloud_sync": true,
    "multi_agent_court": true,
    "background_study_budget_minutes_per_day": 60,
    "dashboard": "full"
  }
}
```

Feature flags ska cacheas lokalt.

---

## 6. Betalplattform

Möjliga val:

| Plattform | Fördel | Nackdel |
|---|---|---|
| Stripe | bäst kontroll | mer setup |
| LemonSqueezy | enklare global VAT | mindre kontroll |
| Paddle | merchant of record | tyngre setup |

Rekommendation första fas: LemonSqueezy eller Stripe efter bot-review.

---

## 7. Website-sidor

| Sida | Syfte |
|---|---|
| `/` | Hunds vision: agenten som lever i din hårdvara |
| `/install` | one-liner install |
| `/pricing` | tiers |
| `/docs` | setup, commands, privacy |
| `/privacy` | exakt telemetry-policy |
| `/changelog` | vad Hund lärt sig |
| `/court` | public court verdicts |
| `/dashboard` | stats/domains/base stats/sync |
| `/account` | subscription/devices |

---

## 8. Dashboard MVP

Dashboard ska visa:

- devices,
- Hund version,
- active domains,
- base stats,
- token/cost/latency summary,
- learning opt-in status,
- update channel,
- subscription tier,
- sync health.

Ingen raw data visas eller skickas utan opt-in.

---

## 9. Limits som känns rättvisa

Bra limits:

- antal aktiva mastery-domäner,
- study-agent budget,
- court-agent budget,
- cloud sync devices,
- dashboard retention,
- hosted credits.

Dåliga limits:

- safety,
- privacy,
- bugfixar,
- data export,
- local basic use.

---

## 10. Acceptance criteria

1. Gratisversionen kan installeras och användas på riktigt.
2. Subscription påverkar kapacitet, inte säkerhet.
3. `hund subscription explain-limits` förklarar tydligt.
4. Offline grace period finns.
5. Feature flags kan testas lokalt.
6. Website pricing är transparent.
7. Privacy-policy finns innan opt-in upload.

---

## 11. Öppna frågor för bot-review

1. Vilka limits känns mest rättvisa?
2. Ska free ha 1 eller 2 mastery-domäner?
3. Ska Pack ha sync eller bara fler domains?
4. Ska hosted credits vara addon eller included?
5. Vilken betalplattform passar bäst tidigt?
