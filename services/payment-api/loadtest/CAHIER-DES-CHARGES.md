# Cahier des charges — loadtest (payment-api)

## 1. Quoi et pourquoi

Un **générateur de charge** pour `payment-api`, livrable d'ingénierie de la résilience.
Il répond à deux besoins du sujet :

1. **Capacité / dimensionnement** — documenter le débit soutenable et la latence de l'API
   sous charge concurrente, chiffres qui alimentent les cibles RTO et l'analyse de
   capacité de [`docs/pca-pra.md`](../../../docs/pca-pra.md).
2. **Distinction disponibilité vs compromission** — fournir une **charge légitime de
   référence** (trafic nominal intense) à opposer au scénario offensif `service_flood`
   (cf. sujet §2, §3.4) : le modèle ML doit distinguer une montée en charge normale d'un
   flood malveillant. Ce harnais produit la baseline « charge normale ».

Ce n'est **pas** un test de justesse métier (couvert par les tests pytest du service et le
test d'intégration PostgreSQL concurrent). Il observe le **comportement sous charge** :
débit, latence (p50/p95/p99/max), taux d'erreur.

## 2. Contraintes de contexte

- **Poste de dev sans Docker ni PostgreSQL** (cf. `docs/pca-pra.md` : validation live en
  recette uniquement). → La cible **par défaut doit être auto-portante** : pas de serveur,
  pas de port, pas de base externe. Retenu : la vraie app FastAPI montée **in-process** via
  le transport ASGI de httpx, sur **SQLite fichier (WAL)** pour tolérer la concurrence (la
  base en mémoire `StaticPool` = une seule connexion, inadaptée à un test de charge).
- **Pas de dépendance nouvelle** (pas d'ajout `pip` type Locust/k6 sur le poste) → le
  harnais n'utilise que des dépendances **déjà présentes** du service : `httpx`, `jwt`,
  `sqlalchemy`, `asyncio`.
- Reproductibilité → graine aléatoire fixe par défaut.

## 3. Exigences fonctionnelles

| # | Exigence |
|---|---|
| F1 | Deux cibles : **in-process** (défaut) et **live** (`--url`, login + découverte des comptes réels). |
| F2 | Charge en **boucle fermée** à concurrence paramétrable, pilotée par **durée** (`-d`) ou **volume** (`-n`). |
| F3 | **Mélange pondéré** des trois endpoints métier (comptes, historique, virement), configurable (`--mix`). |
| F4 | Les virements n'épuisent jamais le solde (montant d'1 cent, comptes largement provisionnés) → la charge d'écriture reste de l'écriture, pas des rejets. |
| F5 | Agrégation **globale et par endpoint** : nombre, erreurs, débit (req/s), p50/p90/p95/p99/max, histogramme des statuts HTTP. |
| F6 | Rapport lisible (console) **et** export **JSON** (`--json`). |
| F7 | **Portes SLO** : `--max-p95-ms`, `--max-error-rate` → code de sortie `2` si dépassées (intégrable en garde). |

## 4. Exigences non-fonctionnelles

- **Isolation** : la base SQLite in-process vit dans un répertoire temporaire, détruit en
  fin de run ; aucun artefact résiduel dans le dépôt.
- **Silence** : l'app est passée en `LOG_LEVEL=WARNING` pendant la charge pour ne pas noyer
  le rapport sous les logs JSON `transaction_created`.
- **Garde réseau** : le mode in-process n'ouvre **aucun socket** (transport ASGI) — testé.
- **Lint/format** : conforme `ruff` (config racine `ruff.toml`).

## 5. Critères d'acceptation (Definition of Done)

- [x] `python loadtest/loadgen.py` produit un rapport avec **0 erreur** sur le profil par défaut.
- [x] Modes `-d` (durée) et `-n` (volume) fonctionnels ; export `--json` valide.
- [x] Portes SLO : dépassement ⇒ code de sortie `2` (vérifié par test).
- [x] `tests/test_loadtest_smoke.py` **vert** (11 tests) ; suite payment-api complète verte (65 passed, 1 skipped).
- [x] `ruff check` / `ruff format --check` clean.
- [x] README du composant + cette fiche + ligne ROADMAP à jour.

## 6. Limites connues / suites

- Les **chiffres in-process sont dominés par SQLite** (un seul *writer*) — ils valident le
  comportement, pas la capacité réelle. Les **mesures officielles de capacité** se prennent
  en mode `--url` contre la stack PostgreSQL en recette J3/J4, et doivent être reportées
  dans `docs/pca-pra.md §4.3`.
- Modèle **boucle fermée** (concurrence fixe), pas à débit d'arrivée imposé (*open model*).
  Suffisant pour une baseline ; un profil à arrivées Poisson serait la suite si l'on veut
  modéliser la saturation au plus près.
- Pas de rampe (montée progressive) : la concurrence est constante sur toute la fenêtre.
