# hund — Fristående AI-kompanjon & Minnessystem

Detta är ett fristående personapaket, minnessystem och runtime-lager för den symbiotiska AI-kompanjonen **hund** på Windows.

hund är byggd för att kunna väckas på en ny dator, analysera aktuell hårdvara/miljö och fylla i sin miljö själv.

---

## Systemstruktur

```text
hund-system/
├── AGENTS.md                    - Instruktioner för AI-agenter som öppnar denna mapp
├── README.md                    - Denna guide
├── hund.md                      - Hunds persona och identitet
├── RUNTIME_POLICY.md            - Operativ intelligens: verktyg, säkerhet, verifiering
├── SKILL.md                     - Startup- och minnes-skill
├── REASONING_BANK.md            - Rå minneslogg
├── memory_summary.md            - Konsoliderat långtidsminne
├── .state/
│   └── manifest.json            - Maskinläsbar karta över Hund-systemet
├── rules/
│   ├── PROTECTED_PATHS.md       - Filer som kräver extra försiktighet
│   └── FILE_ROUTING.md          - Var nya filer ska hamna
├── skills/
│   ├── SKILL_INDEX.md           - Register över hunds skills
│   ├── memory-management/
│   │   └── SKILL.md
│   ├── safety-and-verification/
│   │   └── SKILL.md
│   └── windows-introspection/
│       └── SKILL.md
└── scripts/
    ├── boot_hund.ps1            - Kör init + minnessynk + validering
    ├── start_hund.ps1           - Kompatibel officiell entrypoint till boot
    ├── collect_environment.ps1  - Kompatibel entrypoint till miljöanalys
    ├── init_hund.ps1            - Analyserar aktuell dator och uppdaterar miljöblock
    ├── sync_memory.ps1          - Bygger memory_summary.md från REASONING_BANK.md
    ├── validate_hund.ps1        - Kontrollerar struktur, encoding och scripts
    ├── verify_hund.ps1          - Kompatibel entrypoint till validering
    ├── repair_encoding.ps1      - Normaliserar textfiler vid encodingproblem
    └── hund_common.ps1          - Delade säkra filfunktioner
tests/
├── verify_structure.ps1         - Regressionstest för struktur
├── verify_encoding.ps1          - Regressionstest för UTF-8/mojibake
├── verify_memory.ps1            - Regressionstest för minnesformat
└── verify_startup.ps1           - Kör full boot på temp-kopia
```

---

## Snabbstart på ny Windows-dator

Öppna PowerShell i `hund-system/` och kör:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\boot_hund.ps1
```

Kompatibelt alias:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_hund.ps1
```

Detta gör tre saker:

1. analyserar aktuell OS/CPU/RAM/GPU/hostname,
2. skriver miljön till `hund.md` och `.state/environment.json`,
3. synkar minnet och validerar systemet.

När scriptet är klart: ladda dessa filer i din AI-klient som system-/projektkontext:

```text
hund.md
RUNTIME_POLICY.md
memory_summary.md
SKILL.md
rules/PROTECTED_PATHS.md
rules/FILE_ROUTING.md
skills/SKILL_INDEX.md
```

---

## Viktig princip

`hund.md` är själ och persona.

`RUNTIME_POLICY.md`, `rules/`, `skills/` och `scripts/` är intelligenslagret runt själen.

Ändra inte hunds röst för att göra hund smartare. Gör runtime-lagret starkare.

---

## Minnesloop

1. Under arbete skriver hund hållbara lärdomar i `REASONING_BANK.md`.
2. Vid sessionens slut körs:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync_memory.ps1
```

3. Nästa session laddar `memory_summary.md`.

Minnesposter ska följa blockformatet:

```text
[YYYY-MM-DD] [DOMÄN] Lärdom: ...
Kontext: ...
Regel: ...
```

Tillåtna domäner:

- `SYSTEM`
- `PERSONAL`
- `SKILLS`
- `BEHAVIOR`
- `PROJECT`
- `SAFETY`

---

## Validering

Kör när som helst:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_hund.ps1
```

Kompatibelt alias:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_hund.ps1
```

Validatorn kontrollerar:

- att obligatoriska filer finns,
- att textfiler är giltig UTF-8,
- att mojibake inte har smugit in,
- att `hund.md` har miljömarkörer,
- att PowerShell-scripten parser utan fel,
- att skyddade filer finns kvar.

Regressionstester:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\verify_structure.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\verify_encoding.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\verify_memory.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\verify_startup.ps1
```

---

## Backup

Scripts skapar automatiska backups i:

```text
_backups/auto-YYYYMMDD-HHMMSS-<reason>/
```

Manuell backup från denna uppgradering ligger i `_backups/`.
