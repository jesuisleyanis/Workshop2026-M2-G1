---
name: resilience-component
description: Standard de qualité pour créer ou faire évoluer un composant du monorepo RESILIENCE-ALPHA. Utilise cette skill chaque fois que tu construis, étends ou refactores un service, un module ML, le moteur de remédiation, un front, ou un élément d'infra — pour garantir le format « cas d'école » (CDC + README + code conforme aux contrats + tests + mise à jour de la roadmap).
---

# Standard de composant RESILIENCE-ALPHA

Toute contribution à un composant suit ce standard. Il matérialise la Definition of Done du projet.

## 1. Avant de coder

- Lire `docs/contracts.md` (interfaces transverses) et le `CAHIER-DES-CHARGES.md` du composant.
- Identifier l'exigence du sujet couverte (`R#` dans `CAHIER-DES-CHARGES.md`) et la ligne de `ROADMAP.md`.

## 2. Structure attendue d'un composant

```
<composant>/
├── CAHIER-DES-CHARGES.md   # rôle, périmètre, R# couvertes, interfaces, sécurité, critères d'acceptation
├── README.md               # architecture interne, lancement, test, variables d'env
├── <code>                  # app/, src/, main.py…
├── tests/                  # unitaires ; e2e si chaîne de démo
├── Dockerfile              # durci : slim, non-root, healthcheck (si conteneurisé)
└── requirements.txt / package.json
```

## 3. Conformité aux contrats (vérifier systématiquement)

- **Logs** : JSON une ligne, champs obligatoires du contrat §1, événements normalisés.
- **Métriques** : préfixe `resilience_`, noms/labels du contrat §2, endpoint `/metrics`.
- **Événement d'anomalie** (detector) : schéma exact du contrat §3, `incident_type` dans l'énumération.
- **Table de décision** (remediation) : lire `remediation/decision_table.yml`, ne pas coder les règles en dur.
- **Health** : `/health` et `/ready`. **Codes retour** scripts : 0/1.

## 4. Sécurité (non négociable)

- Non-root, `cap_drop: ALL`, limites ressources, pas d'exposition réseau hors WAF.
- Secrets via SOPS uniquement, jamais en clair.
- Pour la remédiation : docker-socket-proxy, API authentifiée, hors `edge`, garde-fous.

## 5. Tests (obligatoire avant ✅)

- Une assertion par règle métier et par contrat d'interface.
- Cas d'erreur + chemins de sécurité.
- Lancer les tests, montrer le vert. Déléguer au besoin au sous-agent `test-engineer`.

## 6. Documentation + avancement

- Mettre à jour `README.md`/`CAHIER-DES-CHARGES.md` du composant.
- Mettre à jour la ligne de `ROADMAP.md` (statut + preuve) et la barre d'avancement de phase.
- Si une interface change : mettre à jour `docs/contracts.md` et prévenir dans le journal de décisions.

## Rappel

Ne jamais marquer une tâche ✅ si : les tests échouent, la doc n'est pas à jour, ou un contrat d'interface est violé.
