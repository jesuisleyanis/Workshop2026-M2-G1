# Architecture — PROJECT RESILIENCE-ALPHA

> Vue d'ensemble technique. Les interfaces détaillées sont dans [`contracts.md`](contracts.md) ; le cadrage dans [`../CAHIER-DES-CHARGES.md`](../CAHIER-DES-CHARGES.md).

## Vue logique

```mermaid
flowchart TB
    ATT["🖥️ PC Attaquant<br/>(banc d'essai)"] -->|HTTPS 443| WAF

    subgraph edge["réseau edge — seul HTTP exposé (80/443)"]
        WAF["WAF<br/>Nginx + ModSecurity + CRS"]
    end

    subgraph app["réseau app — interne"]
        FRONT["front (React/Vite)"]
        PAY["payment-api (FastAPI)"]
        AUTH["auth (FastAPI)"]
        COL["collector"]
        DET["detector<br/>ML · IsolationForest"]
        REM["Moteur de remédiation (FastAPI)<br/>table de décision §4"]
        PROXY["docker-socket-proxy"]
        DASH["dashboard"]
    end

    subgraph data["réseau data — internal:true"]
        PG[("postgres")]
        PGEXP["pg-exporter"]
    end

    subgraph obs["réseau obs — internal:true"]
        PROMTAIL["promtail"]
        LOKI["loki"]
        PROM["prometheus"]
        CAD["cadvisor"]
        GRAF["grafana<br/>dashboards + SOC rules"]
        ALERT["alertmanager"]
    end

    subgraph ai["réseau ai — optionnel (PC IA)"]
        ASSIST["assistant RAG<br/>Ollama ≤8B + LangChain + Chroma"]
    end

    WAF --> FRONT & PAY & AUTH
    PAY --> PG
    AUTH --> PG
    PGEXP -.-> PG
    PAY -. logs JSON .-> PROMTAIL
    AUTH -. logs JSON .-> PROMTAIL
    PROMTAIL --> LOKI
    PAY -. métriques .-> PROM
    AUTH -. métriques .-> PROM
    CAD -. métriques .-> PROM
    PROM --> GRAF
    PROM --> COL
    COL -->|features §2| DET
    DET -->|AnomalyEvent §3| REM
    PROM --> ALERT -->|webhook SOC| REM
    REM -->|restart conteneur| PROXY
    REM -->|block IP WAF / restore pg_dump| ANS["Ansible"]
    REM -->|boucle de vérification| VTX["verify_tx"]
    REM -.->|SSE : timeline, MTTD/MTTR| DASH

    classDef exposed fill:#fde2e2,stroke:#c0392b,color:#000
    classDef internal fill:#e8f0fe,stroke:#3367d6,color:#000
    class WAF exposed
    class PG,PROM,LOKI,GRAF,ALERT internal
```

## Composants et responsabilités

| Composant | Techno | Réseau | Exposé | Rôle |
|---|---|---|---|---|
| waf | Nginx+ModSecurity+CRS | edge, app | **oui (80/443)** | Filtrage applicatif, unique point d'entrée HTTP, blocage IP |
| front | React/Vite/TS/Tailwind | app | via WAF | Interface de paiement utilisateur |
| payment-api | FastAPI | app | via WAF | Comptes, transactions fictives |
| auth | FastAPI | app | via WAF | Login/register, JWT, rate-limit |
| postgres | PostgreSQL 16 | data | non | Persistance (comptes, transactions) |
| prometheus | Prometheus | obs | non | Métriques |
| loki + promtail | Loki | obs | non | Logs centralisés (fonction SOC) |
| grafana | Grafana | obs | non | Dashboards + règles d'alerte SOC |
| alertmanager | Alertmanager | obs | non | Routage d'alertes → remédiation |
| cadvisor | cAdvisor | obs | non | CPU/RAM par conteneur |
| waf-exporter | Python (`security/waf/waf_exporter.py`) | obs | non | Audit ModSecurity → `resilience_waf_blocked_total{rule}` (:9188) |
| collector | Python | app | non | Construit le vecteur de features (15 s) |
| detector | FastAPI + scikit-learn | app | non | Score ML, émet l'AnomalyEvent |
| remediation | FastAPI + ansible-runner | app | non | Décision + actions + vérification |
| docker-socket-proxy | HAProxy (liste blanche stricte) | app | non | Médie l'accès Docker (verbes limités) |
| mosquitto | MQTT | app | `192.168.137.1:1883` (`iot`) | Transporte les états LED de `auth` vers l'ESP8266 |
| dashboard | React/Vite/TS/Tailwind | app/obs | via WAF/interne | Supervision, timeline, MTTD/MTTR |
| assistant | FastAPI + LangChain + Ollama | ai | non | RAG opérateur (lecture seule) |

## Flux de la reprise autonome (chemin critique de la démo)

Pour l'IoT, le navigateur du back-office appelle `auth` via le WAF ; `auth` publie ensuite
un état sur Mosquitto via le réseau Docker `app`. L'ESP8266, connecté au PA, s'abonne
au broker sur `192.168.137.1:1883`. Le WAF traite HTTP/HTTPS ; le
`docker-socket-proxy` ne sert qu'aux actions Docker de la remédiation. Le client MQTT
dans `auth` reste à raccorder (lot L5-2).

1. **avant** — `verify_tx` → transaction fictive OK (exit 0).
2. **attaque** — scénario lancé depuis le PC Attaquant vers le WAF.
3. **détection** — collector agrège les métriques → detector score via IsolationForest → dépassement de seuil → `AnomalyEvent` (type d'incident classé) envoyé (authentifié) au moteur.
4. **remédiation** — le moteur sélectionne les actions dans `decision_table.yml`, les exécute (restart via proxy / block IP via Ansible / restore dump), en respectant cooldown/max_attempts/dry_run.
5. **après** — boucle de vérification : `verify_tx` OK → incident clos, MTTD/MTTR calculés, timeline poussée au dashboard. **Sans intervention humaine.**

## Choix structurants (ADR)

Voir [`adr/`](adr/). Résumé : mono-langage Python/FastAPI, SOC = règles Loki/Grafana, remédiation via docker-socket-proxy (jamais le socket brut), attaque depuis PC physique pour la démo notée, Ollama déportable sur PC IA.

## Contraintes de ressources (16 Go)

Profil Compose `demo` = chemin critique minimal (WAF, waf-exporter, front, payment-api, auth, postgres, prometheus, loki, promtail, grafana, collector, detector, remediation, dashboard). Observabilité complète (`alertmanager`, `cadvisor`, `pg-exporter`) et `ai` (Ollama) en profils additionnels, l'IA de préférence sur le PC IA.
