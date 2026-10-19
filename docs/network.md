# Réseau & exposition — PROJECT RESILIENCE-ALPHA

> Couvre **R19**. Principe directeur du sujet : **seuls les services nécessaires sont exposés** ; base de données, secrets, interfaces de gestion et API internes restent internes.

## Postes et adressage

| Poste | Rôle | Adresse |
|---|---|---|
| PC Hôte | Exécute toute la stack ; publie **uniquement** le WAF | `192.168.137.1` (hotspot `RESILIENCE-G1`) |
| PC Attaquant | Banc d'essai Red Team, atteint la cible via le WAF | IP hotspot |
| PC IA (option) | Héberge Ollama, exposé en API sur le LAN du groupe | IP hotspot |

Point d'accès : partage de connexion Windows **`RESILIENCE-G1`**, sous-réseau `192.168.137.0/24`.

## Réseaux Docker (isolation)

| Réseau | `internal` | Services | Ports publiés |
|---|---|---|---|
| `edge` | non | waf | **80, 443** (les seuls publiés) |
| `app` | oui | front, payment-api, auth, collector, detector, remediation, docker-socket-proxy, dashboard, assistant | aucun |
| `data` | **oui** | postgres, pg-exporter, remediation (uniquement pour `pg_restore` : correction de corruption) | aucun |
| `obs` | oui | prometheus, loki, promtail, grafana, alertmanager, cadvisor | aucun (accès via tunnel/port-forward local pour le dev) |

- `data` est en `internal: true` : Postgres et les secrets ne sont **jamais** joignables depuis le hotspot.
- Aucun service autre que le WAF ne fait de `ports:` dans `docker-compose.yml`. Rien sur `0.0.0.0` hors WAF.
- Le moteur de remédiation est sur `app` + `data` (restauration Postgres en direct, sans `docker exec`) — **jamais** sur `edge`, aucun `ports:`.

## Pare-feu Windows (PC Hôte)

Règle entrante : autoriser **uniquement** `TCP 80, 443` depuis `192.168.137.0/24`. Tout le reste bloqué en entrée.

```powershell
New-NetFirewallRule -DisplayName "RESILIENCE WAF" -Direction Inbound `
  -Action Allow -Protocol TCP -LocalPort 80,443 -RemoteAddress 192.168.137.0/24
```

## Vérification de l'exposition

```bash
# Depuis le PC Attaquant : seul le WAF répond
curl -k https://192.168.137.1/            # 200/403 (WAF)
curl    http://192.168.137.1:5432/        # doit échouer (Postgres non exposé)
curl    http://192.168.137.1:8005/        # doit échouer (remédiation non exposée)

# Audit local de la config
security/hardening/audit.sh
```

En cas de difficulté matérielle : s'adresser au coach. **Contourner une politique de sécurité n'est jamais une solution admise** (sujet §4).
