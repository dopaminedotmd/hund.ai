---
name: safety-and-verification
description: Säker filhantering, backup och verifiering för hund.
platforms: [windows]
---

# safety-and-verification

## När skillen används

- Före filändringar.
- Före scriptkörning med side effects.
- Före radering, flytt eller overwrite.

## Rutin

1. Läs relevant fil.
2. Kontrollera `rules/PROTECTED_PATHS.md`.
3. Ta backup vid risk.
4. Gör minsta nödvändiga ändring.
5. Läs tillbaka eller kör validator.
6. Rapportera faktisk output.

## Stopplägen

Stoppa och fråga William vid:

- radering,
- flytt,
- ändring utanför hund-system,
- credentials/secrets,
- osäker målfil,
- validering som misslyckas.
