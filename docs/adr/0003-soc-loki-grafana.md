# ADR 0003 — Fonction SOC via Loki/Grafana plutôt que Wazuh

- **Statut :** accepté (J1)
- **Contexte :** le sujet demande « un SIEM **ou** une fonction SOC intégrée à votre dispositif de supervision ». Wazuh single-node est lourd ; le PC Hôte dispose de 16 Go de RAM partagés avec toute la stack (dont potentiellement Ollama).
- **Décision :** la fonction SOC est assurée par la stack d'observabilité déjà présente — règles d'alerte Grafana + Loki ruler corrélant logs WAF/auth/API (voir `infra/grafana/provisioning/alerting/soc-rules.yml`). Wazuh reste possible en profil Compose optionnel si une machine le permet.
- **Conséquences :**
  - (+) Aucune empreinte mémoire supplémentaire ; réutilise Prometheus/Loki/Grafana.
  - (+) Conforme à la lettre du sujet (« fonction SOC intégrée »). Elastic explicitement écarté par le sujet.
  - (−) Moins de fonctionnalités qu'un vrai SIEM (pas de gestion de cas) ; suffisant pour le périmètre démontré, à assumer dans le dossier.
