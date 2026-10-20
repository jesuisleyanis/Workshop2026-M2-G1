# Réseau & exposition — PROJECT RESILIENCE-ALPHA

> Couvre **R19**. Principe directeur du sujet : **seuls les services nécessaires sont exposés** ; base de données, secrets, interfaces de gestion et API internes restent internes.

## Postes et adressage

| Poste | Rôle | Adresse |
|---|---|---|
| PC Hôte | Exécute la stack ; publie le WAF HTTP et, avec le profil `iot`, Mosquitto MQTT | `192.168.137.1` (hotspot `RESILIENCE-G1`) |
| PC Attaquant | Banc d'essai Red Team, atteint la cible via le WAF | IP hotspot |
| PC IA (option) | Héberge Ollama, exposé en API sur le LAN du groupe | IP hotspot |

Point d'accès : partage de connexion Windows **`RESILIENCE-G1`**, sous-réseau `192.168.137.0/24`.

## Réseaux Docker (isolation)

| Réseau | `internal` | Services | Ports publiés |
|---|---|---|---|
| `edge` | non | waf | **80, 443** (HTTP/HTTPS) |
| `app` | non | front, payment-api, auth, mosquitto (`iot`), collector, detector, remediation, docker-socket-proxy, dashboard, assistant | **1883** sur `192.168.137.1` pour Mosquitto (`iot`) |
| `data` | **oui** | postgres, pg-exporter, remediation (uniquement pour `pg_restore` : correction de corruption) | aucun |
| `obs` | oui | prometheus, loki, promtail, grafana, alertmanager, cadvisor, waf-exporter | aucun (accès via tunnel/port-forward local pour le dev) |

- `data` et `obs` sont en `internal: true` : Postgres, secrets et observabilité ne sont **jamais** joignables depuis le hotspot ni ne sortent vers Internet.
- `app` n'est **pas** `internal` : c'est le seul réseau avec sortie (pull d'images, modèles Ollama). Mosquitto est la seule exception à l'absence de port publié sur ce réseau, et seulement dans le profil `iot`.
- Le WAF est l'unique entrée HTTP de la plateforme. MQTT ne passe pas par le WAF : le broker écoute directement sur l'interface du PA. Rien d'autre n'est publié sur `0.0.0.0` hors WAF.
- Le moteur de remédiation est sur `app` + `data` (restauration Postgres en direct, sans `docker exec`) — **jamais** sur `edge`, aucun `ports:`.

## Pare-feu Windows (PC Hôte)

Règle entrante : autoriser `TCP 80, 443` depuis `192.168.137.0/24` ; avec le profil `iot`, autoriser aussi `TCP 1883` depuis ce sous-réseau. Tout le reste reste bloqué en entrée.

```powershell
New-NetFirewallRule -DisplayName "RESILIENCE WAF" -Direction Inbound `
  -Action Allow -Protocol TCP -LocalPort 80,443 -RemoteAddress 192.168.137.0/24

# Seulement si le profil iot est activé :
New-NetFirewallRule -DisplayName "RESILIENCE MQTT" -Direction Inbound `
  -Action Allow -Protocol TCP -LocalPort 1883 -LocalAddress 192.168.137.1 `
  -RemoteAddress 192.168.137.0/24
```

## Vérification de l'exposition

```bash
# Depuis le PC Attaquant : le WAF répond ; MQTT exige des identifiants si iot est actif
curl -k https://192.168.137.1/            # 200/403 (WAF)
curl    http://192.168.137.1:5432/        # doit échouer (Postgres non exposé)
curl    http://192.168.137.1:8005/        # doit échouer (remédiation non exposée)

# Audit local de la config
security/hardening/audit.sh
```

En cas de difficulté matérielle : s'adresser au coach. **Contourner une politique de sécurité n'est jamais une solution admise** (sujet §4).
