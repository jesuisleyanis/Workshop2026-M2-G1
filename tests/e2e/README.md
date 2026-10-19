# Tests end-to-end

Rejouent la chaîne complète **avant → attaque → détection → remédiation → après** contre une stack réelle.

```bash
make up            # lève la stack (profil demo)
make seed          # données fictives
RESILIENCE_E2E=1 pytest tests/e2e -q
```

`web_attack` a son propre test : la source attaquante est bloquée par la remédiation, donc le `verify_tx` lancé depuis l'hôte (même IP) serait lui aussi refusé ; la preuve de reprise se lit dans le journal du moteur (`status == closed`). La liste de blocage est vidée avant et après (renommage : le WAF se recharge seul).

Désactivés par défaut (sautés) pour ne pas dépendre de Docker dans la suite unitaire. Chaque scénario de `attacks/scenarios/` est rejoué et doit se solder par un `verify_tx` OK **sans intervention humaine** — c'est la preuve attendue par le jury (Axe 1).
