# ADR 0001 — Mono-langage Python/FastAPI pour le backend

- **Statut :** accepté (J1)
- **Contexte :** le sujet autorise Node.js / Python-FastAPI / Go pour les API. Sprint de 4 jours, équipe pluridisciplinaire, besoin de ML (scikit-learn).
- **Décision :** tous les services backend (payment-api, auth, detector, collector, remediation, assistant) en Python 3.12 + FastAPI.
- **Conséquences :**
  - (+) Une seule chaîne d'outillage (ruff, pytest), synergie directe avec scikit-learn, OpenAPI gratuit, lib partagée `resilience_common` réutilisée partout.
  - (+) Montée en charge de l'équipe plus rapide sous contrainte de temps.
  - (−) Pas de vitrine multi-langage ; acceptable (le sujet valorise la cohérence et la maîtrise, pas la diversité).
