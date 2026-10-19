# Tests end-to-end

Rejouent la chaîne complète **avant → attaque → détection → remédiation → après** contre une stack réelle.

```bash
make up            # lève la stack (profil demo)
make seed          # données fictives
RESILIENCE_E2E=1 pytest tests/e2e -q
```

Désactivés par défaut (sautés) pour ne pas dépendre de Docker dans la suite unitaire. Chaque scénario de `attacks/scenarios/` est rejoué et doit se solder par un `verify_tx` OK **sans intervention humaine** — c'est la preuve attendue par le jury (Axe 1).
