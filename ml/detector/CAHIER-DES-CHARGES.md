# Cahier des charges — ml/detector

**Pourquoi.** C'est le maillon « détection » de la boucle zero-touch (sujet Axe 1) : transformer les métriques en un événement
d'anomalie exploitable par le moteur de remédiation, **sans humain**. R8 : la décision vient du modèle ML.

**Périmètre.**
- Charge `model.joblib` + `baseline_stats.json` (après vérification du sha256), relève le collector toutes les 15 s.
- Calcule `anomaly_score` (IsolationForest), l'expose en `resilience_anomaly_score{service}` (via `resilience_common`).
- Score >= seuil -> construit un `AnomalyEvent` (contrat §3, validé par pydantic), log `anomaly_detected`, `POST /events` sur la remédiation
  avec `Authorization: Bearer <REMEDIATION_TOKEN>`.
- `GET /health`, `/ready`, `/metrics`, `/api/v1/status`. Image durcie (slim, non-root uid 10003, healthcheck).

**Règles de décision.** (1) décideur : score ML >= seuil ; (2) garde-fou statistique |z| >= `guardrail_z` — filet, documenté comme tel ;
(3) `incident_type` par heuristique de routage de `ml/shared`. Anti-spam : un événement par `EVENT_COOLDOWN_SECONDS` (60 s) ; pas de
cooldown si l'envoi a échoué (nouvel essai au tick suivant ; 3 tentatives avec backoff par envoi, aucun retry sur 400/401/403/422).

**Sécurité.** Token via secret monté (`REMEDIATION_TOKEN_FILE`, SOPS) ou variable d'env, jamais loggé ; `/ready` est KO sans token.
Modèle refusé si le hash ou la liste de features ne correspondent pas. Réseau `app` interne, aucun port publié, `cap_drop: ALL` / `read_only` compatibles.

**Limites.** Détection par fenêtre de 15 s (MTTD >= 1 tick) ; un détecteur par déploiement scorant le système globalement
(`service` = `TARGET_SERVICE`, défaut `payment-api`) ; l'attribution fine par service n'est pas modélisée.
