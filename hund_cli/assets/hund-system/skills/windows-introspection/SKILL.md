---
name: windows-introspection
description: Analysera Windows-miljö, hårdvara och körkontext för hund.
platforms: [windows]
---

# windows-introspection

## När skillen används

- Första uppstart på ny dator.
- Efter hårdvaru-/OS-byte.
- När William frågar vilken miljö hund körs i.

## Rutin

1. Kör `scripts/init_hund.ps1`.
2. Verifiera att `hund.md` uppdaterats mellan miljömarkörerna.
3. Verifiera att `.state/environment.json` skapats.
4. Rapportera bara faktisk detekterad miljö.

## Risker

- Hårdkoda aldrig Williams gamla dator.
- Lita inte på gammalt miljöblock utan ny körning.
- Windows PowerShell 5.1 kräver encoding-disciplin.

## Verifiering

Kör `scripts/validate_hund.ps1` efter init.
