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
├── blocklist/blocked_ips.conf         # liste de deny rechargeable (gérée par la remédiation) ; le DOSSIER est monté
├── docker-entrypoint.d/97-audit-rotate.sh  # borne le journal d'audit (troncature au seuil)
├── Dockerfile.exporter                # image du service waf-exporter
├── waf_exporter.py                    # journal d'audit -> resilience_waf_blocked_total + event waf_blocked
├── requirements.txt                   # dépendances de l'exporter
└── tests/                             # exporter, modèles nginx/compose/playbook, vraie image (opt-in)
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
| `LOGLEVEL` | `error` | les **causes des 502** (`connect() failed`, `could not be resolved`, `upstream timed out`) doivent rester visibles. À ce niveau nginx écrit la requête complète (query string, donc jetons éventuels) et ModSecurity `[data "…"]` / `(Value: …)` : **Promtail les masque avant Loki** (étapes `replace`, `infra/promtail/promtail-config.yml`) |
| `AUDIT_LOG_MAX_BYTES` / `AUDIT_ROTATE_INTERVAL_S` | 16 Mio / 5 s | seuil de troncature du journal d'audit (voir ci-dessous) |

### Ce qui est journalisé, et où (vérifié)

Test : login avec le mot de passe `Zq9' OR 1=1--secret` et requête `?token=TOKZQ9&id=1' OR '1'='1` (toutes deux bloquées, 403).

| Sortie | Destination | Secret retrouvé |
|---|---|---|
| access log JSON | Promtail → Loki | **aucun** (pas de query string, pas de corps) |
| `error_log` (stderr du WAF, niveau `error`) | Promtail → Loki | **aucun après masquage** : query string de `request:`/`upstream:`/`referrer:`, `[data "…"]` et `(Value: …)` retirés par Promtail (vérifié avec l'image Promtail réelle). Le log **local** du conteneur (`docker logs`) les garde : lecture réservée à l'opérateur de l'hôte |
| event `waf_blocked` | waf-exporter → Loki | **aucun** (IP, chemin sans query, règle) |
| journal d'audit `audit.json` | volume `waf-logs` | **oui : la donnée appariée par la règle** (partie H) |

**Risque résiduel assumé** : ModSecurity v3 ne sait pas masquer la donnée appariée (les actions `sanitise*` de v2 n'existent pas). Le journal d'audit est donc cloisonné : volume **tmpfs** (en mémoire, non persistant, 64 Mo max), dossier `0750 nginx:nginx`, lu en lecture seule par le seul waf-exporter (groupe 101), jamais collecté par Promtail, et limité aux 403.

**Rotation du journal d'audit** : ModSecurity v3 ne fait pas tourner son journal et un tmpfs plein ferait perdre les blocages suivants (waf-exporter ne les compterait plus). `docker-entrypoint.d/97-audit-rotate.sh` (lancé en tâche de fond par l'entrypoint de l'image, sous l'utilisateur `nginx`) **tronque en place** le fichier dès qu'il atteint `AUDIT_LOG_MAX_BYTES` (16 Mio sur 64 Mo de tmpfs : marge pour l'écriture entre deux contrôles de 5 s). ModSecurity écrit en ajout : il continue sur le même inode. waf-exporter détecte la troncature (taille < position, ou début du fichier différent : cas d'un fichier tronqué puis ré-alimenté au-delà de l'ancienne position entre deux sondages) et relit depuis le début. Perte possible : les lignes écrites depuis la dernière lecture de l'exporter (< 0,5 s) au moment de la troncature ; les blocages déjà lus restent comptés (`resilience_waf_blocked_total` ne régresse pas).

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

1. ajoute une ligne `"<ip> 1;"` dans `security/waf/blocklist/blocked_ips.conf` **sur l'hôte**. C'est le **dossier** `security/waf/blocklist/` qui est monté (en lecture seule : un WAF compromis ne peut pas débloquer une source) sur `/etc/nginx/blocklist/`. Un montage du *fichier* seul garderait l'ancien inode quand l'hôte Linux réécrit le fichier par renommage (`lineinfile` d'Ansible) : l'action serait marquée réussie sans que nginx voie la nouvelle liste. Le playbook lit les variables que le moteur envoie : `deny_ip`, `deny_list`, `incident_id` ;
2. déclenche un rechargement à chaud : `docker exec resilience-g1-waf-1 nginx -s reload`.

Les requêtes des IP listées reçoivent **403** (renvoyé avant ModSecurity : pas d'event `waf_blocked`, c'est un blocage de source, pas une règle CRS). **Toute modification du fichier doit être suivie d'un reload**, y compris un retrait manuel. Interface stable — ne pas changer le format sans mettre à jour `remediation/` et `docs/contracts.md`.

> État de la chaîne automatique (suivi au ROADMAP, **I11**) : le nom de variable du playbook est aligné sur le moteur (`deny_ip`)
> et l'écriture-par-renommage est vue par nginx (testé sur la vraie image). **Reste ouvert** : `docker exec … nginx -s reload` n'est
> pas autorisé par `docker-socket-proxy`, et le detector n'émet pas encore `source_ip`. L'action `waf_block_ip` n'est donc pas
> vérifiée de bout en bout : le composant WAF n'est pas marqué ✅ tant que l'e2e `web_attack` n'est pas vert.

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
# Tests sans conteneur : exporter + garanties de sécurité des modèles nginx / compose / playbook / Promtail
python -m pytest security/waf/tests/ -q

# Tests sur la VRAIE image (build + nginx/ModSecurity/CRS contre des backends factices ; Docker requis)
make test-waf          # = WAF_DOCKER_TESTS=1 pytest security/waf/tests

# Images
docker build -t resilience/waf security/waf
docker build -f security/waf/Dockerfile.exporter -t resilience/waf-exporter security/waf

# Contrôles sur la stack levée
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost/                                      # 200
curl -sk -o /dev/null -w '%{http_code}\n' "https://localhost/api/v1/accounts?id=1'%20OR%20'1'='1"  # 403
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost/metrics                               # 404
```
