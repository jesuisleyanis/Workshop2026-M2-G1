# WAF — Nginx + ModSecurity + OWASP CRS

> Couvre **R11** (filtrage applicatif, seul point exposé) et **R19** (publication réseau maîtrisée).

## Rôle

Reverse-proxy unique en frontal de la plateforme. **Seul composant exposé** sur le hotspot (80/443, TLS auto-signé). Protège le front et les API métier via ModSecurity v3 + OWASP CRS 4, et porte la **liste de blocage IP** pilotée par la remédiation.

## Arborescence

```
security/waf/
├── Dockerfile                         # image WAF (base OWASP CRS épinglée, non-root)
├── templates/conf.d/
│   ├── default.conf.template          # serveur : routage, liste de blocage, refus explicites
│   └── logging.conf.template          # access log JSON (contrat §1) sur stdout
├── blocked_ips.conf                   # liste de deny rechargeable (gérée par la remédiation)
├── Dockerfile.exporter                # image du service waf-exporter
├── waf_exporter.py                    # journal d'audit -> resilience_waf_blocked_total + event waf_blocked
├── requirements.txt                   # dépendances de l'exporter
└── tests/                             # tests de l'exporter (parsing, suivi du journal, métrique)
```

## Image

Base **`owasp/modsecurity-crs:4.25.1-nginx-alpine-202609301109-lts`** (tag épinglé : version CRS LTS + build daté). Elle apporte ModSecurity, le CRS, l'utilisateur non-root `nginx` (uid 101) et un entrypoint qui, **au démarrage** :

1. génère le certificat TLS auto-signé (`/etc/nginx/conf/server.{crt,key}`) ;
2. rend les modèles `/etc/nginx/templates/**.template` par `envsubst` (seules les variables d'environnement *définies* sont substituées : `$remote_addr` & co. restent intactes) ;
3. configure ModSecurity et le CRS (`/etc/modsecurity.d/setup.conf`).

On ne remplace que deux modèles (`conf.d/default.conf`, `conf.d/logging.conf`). Choix de configuration (ENV du Dockerfile) :

| Variable | Valeur | Pourquoi |
|---|---|---|
| `PORT` / `SSL_PORT` | `8080` / `8443` | non-root + `cap_drop: ALL` : pas de port < 1024 ; le compose publie `80:8080`, `443:8443` |
| `MODSEC_RULE_ENGINE` | `on` | blocage actif (pas seulement détection) |
| `BLOCKING_PARANOIA` | `1` | PL1 : pas de faux positifs sur le trafic légitime de la démo |
| `MODSEC_AUDIT_LOG` | `/var/log/modsec/audit.json` (JSON, Serial, RelevantOnly) | lu par waf-exporter via le volume `waf-logs` |
| `MODSEC_AUDIT_LOG_PARTS` | `AHZ` | ni en-têtes ni corps journalisés (les parties par défaut B, I, J, E… écriraient jetons `Authorization` et mots de passe). A = IP/URI/code, H = règles déclenchées |
| `MODSEC_AUDIT_LOG_RELEVANT_STATUS` | `^403$` | seuls les **blocages** sont journalisés (pas les 401/429 d'un flood de logins) : taille et exposition bornées |
| `LOGLEVEL` | `crit` | à `error`, nginx écrit dans `error_log` (stderr → Promtail → **Loki**) la requête complète avec sa query string, et ModSecurity la donnée appariée. Les erreurs HTTP restent visibles via le statut de l'access log ; les blocages via waf-exporter |

### Ce qui est journalisé, et où (vérifié)

Test : login avec le mot de passe `Zq9' OR 1=1--secret` et requête `?token=TOKZQ9&id=1' OR '1'='1` (toutes deux bloquées, 403).

| Sortie | Destination | Secret retrouvé |
|---|---|---|
| access log JSON + stderr du WAF | Promtail → Loki | **aucun** (pas de query string, pas de corps, `error_log` à `crit`) |
| event `waf_blocked` | waf-exporter → Loki | **aucun** (IP, chemin sans query, règle) |
| journal d'audit `audit.json` | volume `waf-logs` | **oui : la donnée appariée par la règle** (partie H) |

**Risque résiduel assumé** : ModSecurity v3 ne sait pas masquer la donnée appariée (les actions `sanitise*` de v2 n'existent pas). Le journal d'audit est donc cloisonné : volume **tmpfs** (en mémoire, non persistant, 64 Mo max), dossier `0750 nginx:nginx`, lu en lecture seule par le seul waf-exporter (groupe 101), jamais collecté par Promtail, et limité aux 403.

## Durcissement

| | WAF | waf-exporter |
|---|---|---|
| utilisateur | `nginx` (101) | `wafexp` (10007, + groupe 101) |
| `cap_drop: ALL`, `no-new-privileges` | oui | oui |
| `read_only` | **non** (voir ci-dessous) | oui |
| limites | 256 Mo, 0,5 CPU, 128 pids | 64 Mo, 0,25 CPU, 32 pids |
| réseau / ports | `edge` + `app`, seuls ports publiés de la plateforme (`80:8080`, `443:8443`) | `obs` seul, aucun port publié |

Le WAF n'est pas `read_only` : l'entrypoint de l'image rend sa conf et son certificat au démarrage dans `/etc/nginx` et `/etc/modsecurity.d` ; un tmpfs sur ces dossiers masquerait les règles CRS et les modules de l'image. Risque résiduel : un attaquant qui obtiendrait l'exécution de code dans nginx pourrait modifier la conf rendue (même uid que le worker). Compensé par non-root, `cap_drop: ALL`, `no-new-privileges` et la liste de blocage montée en lecture seule.

## Routage (`default.conf.template`)

| Chemin | Destination |
|---|---|
| `/api/v1/accounts`, `/api/v1/transactions` | `payment-api:8001` |
| `/api/v1/login`, `/api/v1/register` | `auth:8002` |
| toute autre route `/api/`, `/internal/*`, `/metrics` | **404 renvoyé par le WAF** (défense en profondeur) |
| `/` | `front:8080` |
| `/healthz` | sonde locale (127.0.0.1) du healthcheck, 404 depuis le réseau, hors ModSecurity |

- **Backends résolus à chaque requête** (variables + `resolver` Docker) : un service redémarré par la remédiation est retrouvé sans reload, et le WAF démarre même si un backend n'est pas prêt (il répond alors 502).
- `X-Forwarded-For` est **écrasé** par l'IP réelle (pas d'usurpation d'IP auprès des services et du rate-limit de l'auth).
- En-têtes de sécurité posés par le WAF seul (`nosniff`, `DENY`, `no-referrer`), ceux des backends masqués ; en-tête `Server` supprimé.

## Interface de blocage IP (consommée par la remédiation)

L'action `waf_block_ip` / `waf_blacklist_ip` du moteur de remédiation (playbook `infra/ansible/playbooks/waf_deny_ip.yml`) :

1. ajoute une ligne `"<ip> 1;"` dans `security/waf/blocked_ips.conf` **sur l'hôte** (monté en lecture seule dans le conteneur : un WAF compromis ne peut pas débloquer une source) ;
2. déclenche un rechargement à chaud : `docker exec resilience-g1-waf-1 nginx -s reload`.

Les requêtes des IP listées reçoivent **403** (renvoyé avant ModSecurity : pas d'event `waf_blocked`, c'est un blocage de source, pas une règle CRS). **Toute modification du fichier doit être suivie d'un reload**, y compris un retrait manuel. Interface stable — ne pas changer le format sans mettre à jour `remediation/` et `docs/contracts.md`.

> État de la chaîne automatique (constaté à la revue sécurité, hors de ce composant, suivi au ROADMAP) : le playbook attend
> `blocked_ip` alors que le moteur envoie `deny_ip`, et `docker exec … nginx -s reload` n'est pas autorisé par
> `docker-socket-proxy`. La conf nginx (liste + reload) est vérifiée ; l'action `waf_block_ip` de bout en bout ne l'est pas.

> Limite : le fichier est monté seul (bind mount de fichier). Sous Docker Desktop (Windows, poste de démo), une écriture par renommage (comme `lineinfile` d'Ansible) est bien vue par le conteneur (vérifié) ; sur un hôte Linux, un bind mount de fichier garde l'ancien inode après renommage — monter alors le dossier plutôt que le fichier.

## Observabilité (fonction SOC)

- **Access log JSON** (`json_waf`, champs obligatoires du contrat §1, event `http_request`) sur stdout → Promtail → Loki.
- **waf-exporter** (service compose séparé, lecture seule, réseau `obs`, aucun port publié) suit le journal d'audit (`tail -F` : attend sa création, gère troncature/rotation) et, pour chaque requête **bloquée** (403 + au moins une règle) :
  - incrémente `resilience_waf_blocked_total{rule}` (contrat §2), exposée sur `waf-exporter:9188/metrics`, scrapée par Prometheus → feature ML `waf_blocked_per_s` ;
  - écrit l'event `waf_blocked` (contrat §1) → Loki ; label Loki `service="waf-exporter"` (posé par Promtail), interrogé par l'action `confirm_waf_block`.
- Label `rule` : première règle de **détection** (ex. `942100` SQLi), plutôt que l'évaluation du score (`949110`) ou un avertissement protocole (`920350`). Cardinalité bornée aux identifiants du CRS.
- Une ligne de journal inattendue est ignorée, jamais une exception (un crash ferait perdre les blocages pendant le redémarrage).
- Limite : en Docker Desktop, le WAF voit tous les clients de l'hôte sous l'IP de passerelle du réseau `edge` (ex. `172.22.0.1`). À vérifier depuis le PC attaquant avant la démo : si c'est aussi le cas, la liste de blocage et le rate-limit de l'auth viseraient tout le monde.

## Lancement / test

```bash
# Tests de l'exporter (sans conteneur)
python -m pytest security/waf/tests/ -q

# Images
docker build -t resilience/waf security/waf
docker build -f security/waf/Dockerfile.exporter -t resilience/waf-exporter security/waf

# Contrôles sur la stack levée
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost/                                      # 200
curl -sk -o /dev/null -w '%{http_code}\n' "https://localhost/api/v1/accounts?id=1'%20OR%20'1'='1"  # 403
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost/metrics                               # 404
```
