"""Self-improvement — lokala proposals från gap-events.

Säkerhetsmodell (review):
  Hund föreslår + debatterar. Hund publicerar ALDRIG.
  change_type tvingas DEKLARATIV (runtime_policy/skill/hundk/prompt/test).
  Core/engine/safety/updater/redactor = TCB, får ALDRIG föreslås som ändring.
  Mänsklig gate (hund proposals approve/reject) krävs före allt.
"""
