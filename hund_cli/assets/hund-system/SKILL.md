---
name: hund-memory-and-startup
description: >
  Hanterar uppstart, hårdvaru-introspektion, minneshantering, säker verifiering och skill-laddning för hund.
version: 2.0.0
platforms: [windows]
---

# Skill: hund Uppstart, Introspektion & Minnessystem

Denna skill definierar hur hund initierar sig själv på en ny maskin, sparar minnen under sessioner, bygger långtidsminne och verifierar att systemet är friskt.

---

## 1. När denna skill ska användas

Använd alltid denna skill när:

- hund startar i en ny miljö,
- hårdvara eller OS kan ha ändrats,
- `memory_summary.md` behöver uppdateras,
- hund ska skriva till egna systemfiler,
- William ber hund att bli mer stabil, smart eller självständig.

---

## 2. Uppstarts- och introspektionsrutin

Kör vid första uppstart på en ny dator:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\boot_hund.ps1
```

Om endast miljön ska uppdateras:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\init_hund.ps1
```

Detta ska:

1. läsa aktuell Windows-version,
2. läsa CPU,
3. läsa RAM,
4. läsa GPU,
5. läsa hostname,
6. skriva miljön till `hund.md` inom markerat miljöblock,
7. skriva maskinläsbar miljö till `.state/environment.json`,
8. verifiera att ändringen faktiskt hamnade i filen.

hund ska inte hårdkoda Williams nuvarande dator. hund ska analysera den dator där hund väcks.

---

## 3. Minnesloggning under sessionen

När hund fattar viktiga beslut, lär sig nya mönster, eller skapar egna skills, ska hund logga till `REASONING_BANK.md`.

Format:

```text
[YYYY-MM-DD] [DOMÄN] Lärdom: <kort hållbar lärdom>
Kontext: <varför detta spelar roll>
Regel: <konkret regel att följa framöver>
```

Tillåtna domäner:

- `SYSTEM` — hårdvara, operativsystem, programvara
- `PERSONAL` — Williams stabila preferenser
- `SKILLS` — skapade eller uppdaterade skills
- `BEHAVIOR` — förbättringar av hunds eget beteende
- `PROJECT` — långlivade projektmönster
- `SAFETY` — risker, skydd och verifieringskrav

Spara inte engångsstatusar eller tillfälliga resultat.

---

## 4. Minnessynk

Vid sessionens slut eller vid manuell begäran:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync_memory.ps1
```

Synken ska bevara hela blocket: `Lärdom`, `Kontext` och `Regel`.
Den får inte bara kopiera datumraden.

---

## 5. Säker filändring

Innan hund skriver till en fil:

1. Läs filen.
2. Kontrollera `rules/PROTECTED_PATHS.md`.
3. Ta backup om filen är viktig eller befintlig.
4. Skriv ändringen.
5. Läs tillbaka filen.
6. Kör `scripts/validate_hund.ps1` om systemfil ändrats.

---

## 6. Verifiering

Kör:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_hund.ps1
```

Ett godkänt system ska visa `VALIDATION PASSED`.

Om validering misslyckas ska hund inte säga att systemet är klart. hund ska rapportera exakt vilken kontroll som föll.
