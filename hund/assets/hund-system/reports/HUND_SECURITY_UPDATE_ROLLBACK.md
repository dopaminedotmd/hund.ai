# Hund Security, Update & Rollback Plan

> **Syfte:** Ge Hund en fungerande säkerhets- och uppdateringsmodell innan implementation. Detta är en grundplan som andra bottar senare ska granska och vässa.

---

## 1. Grundprincip

Hund får bli självförbättrande, men får aldrig bli självpublicerande.

```text
Hund får föreslå.
Hund får debattera.
Hund får bygga kandidatpatchar.
Hund får aldrig släppa eller applicera core-updates utan admin-gate.
```

---

## 2. Säkerhetslager

| Lager | Funktion |
|---|---|
| Permission Engine | Stoppar riskåtgärder i tools |
| Update Gate | Stoppar självpublicering |
| Signature Verify | Verifierar releases |
| Rollback Store | Kan backa till föregående fungerande version |
| Audit Log | Loggar alla risk- och updatehändelser |
| Policy Lock | Skyddar persona/safety/privacy-regler |
| Court Veto | Safety Auditor kan stoppa update-kandidat |

---

## 3. Update-kanaler

| Kanal | Syfte | Vem får den |
|---|---|---|
| `stable` | säkra releases | alla |
| `beta` | testade förbättringar | supporters/pro/frivilliga |
| `nightly` | experimentella builds | admin/dev endast |
| `local-candidate` | Hunds egna kandidatpatchar | aldrig auto-install |

Stable ska bara innehålla signerade releases.

---

## 4. Release-flöde

```text
local observations
→ proposal
→ court
→ update candidate
→ tests
→ human/admin approval
→ signed release
→ staged rollout
→ health check
→ rollback if broken
```

Ingen genväg runt admin-gate.

---

## 5. Signering och checksums

Varje release ska ha:

```text
release.json
SHA256SUMS.txt
SHA256SUMS.sig
CHANGELOG.md
ROLLBACK.md
```

`release.json` exempel:

```json
{
  "version": "0.3.0",
  "channel": "stable",
  "created_at": "2026-06-18T12:00:00Z",
  "artifacts": [
    {
      "name": "hund-cli-0.3.0-win.zip",
      "sha256": "...",
      "signature": "..."
    }
  ],
  "minimum_safe_version": "0.2.4",
  "rollback_supported": true
}
```

MVP kan börja med SHA256-verifiering. Signering läggs in innan publik release.

---

## 6. Rollback

Innan update sparar Hund:

```text
%LOCALAPPDATA%/hund/backups/releases/<version>/
├── config_snapshot.json
├── package_snapshot.txt
├── hund-system_snapshot.zip
└── rollback_manifest.json
```

Rollback-kommando:

```text
hund update rollback
hund update rollback --to 0.2.4
```

Rollback ska inte radera användarens minne. Den ska backa motor/systemfiler, men bevara lokal data.

---

## 7. Skyddade delar

Följande får inte ändras av auto-update utan explicit migration:

| Del | Regel |
|---|---|
| user config | merge, aldrig overwrite |
| API keys | aldrig läsas/loggas |
| local memory | backup + migration |
| `.hundk` | schema migration, inte overwrite |
| persona | bara signerade, admin-godkända ändringar |
| safety policy | hård granskning |

---

## 8. Update health check

Efter update körs:

```text
hund doctor
hund verify
hund benchmark smoke
hund privacy check
```

Om health check failar:

1. stoppa startup,
2. erbjud rollback,
3. logga failure,
4. skicka anonym crash/update-metadata endast om opt-in.

---

## 9. Threat model

| Risk | Motåtgärd |
|---|---|
| Malicious update | signering + checksum |
| Hund försöker självpublicera | admin gate i kod |
| Prompt injection i learning bank | redaction + schema + court safety veto |
| Supply chain attack | pinned dependencies + lockfile |
| Secret leak i telemetry | redactor + forbidden fields + tests |
| Broken update | rollback + staged rollout |
| Malicious `.hundk` | schema validation + no executable code |
| Tool abuse | Permission Engine |

---

## 10. Acceptance criteria

Första versionen är godkänd när:

1. `hund update check` kan läsa release metadata.
2. `hund update install` verifierar checksum.
3. `hund update rollback` fungerar lokalt.
4. User memory överlever update/rollback.
5. `hund doctor` körs efter update.
6. Safety/persona/privacy-filer kan inte ändras utan explicit release metadata.
7. Broken update simuleras i test och rollback passerar.

---

## 11. Öppna frågor för bot-review

1. Vilken signeringsmodell bör användas första året?
2. Ska update använda egen host, GitHub Releases eller package index?
3. Hur gör vi staged rollout utan tung backend?
4. Vilka filer ska absolut aldrig auto-migreras?
5. Hur stoppar vi malicious learning proposals från att bli code changes?
