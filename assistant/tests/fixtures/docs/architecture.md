# Architecture

Le WAF est le seul composant exposé (ports 80 et 443). Les réseaux data, app et obs sont internes.

## Observabilité
Prometheus collecte les métriques, Loki les logs, Grafana affiche les tableaux de bord.
