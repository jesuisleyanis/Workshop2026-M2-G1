# WAF — Nginx + ModSecurity + OWASP CRS

> Couvre **R11** (filtrage applicatif, seul point d'entrée HTTP) et **R19** (publication réseau maîtrisée).

## Rôle

Reverse-proxy unique en frontal de la plateforme. **Seul composant exposé** sur le hotspot (80/443, TLS auto-signé). Protège le front et les API métier via ModSecurity + le jeu de règles OWASP CRS, et porte la **liste de blocage IP** pilotée par la remédiation.

## Arborescence

```
security/waf/
├── Dockerfile          # image owasp/modsecurity-crs:*-nginx-alpine épinglée, non-root, TLS auto-signé au build
├── nginx.conf          # reverse-proxy + ModSecurity + liste de blocage
├── deny/blocked_ips.conf   # deny-list initiale (vide) ; en stack : volume partagé `waf-deny`
├── docker-entrypoint.d/05-ensure-deny-list.sh  # recrée la deny-list si le volume est vide
├── waf_exporter.py     # waf-exporter : audit ModSecurity -> métrique resilience_waf_blocked_total{rule} + event waf_blocked
├── Dockerfile.exporter # image du waf-exporter (python slim, non-root, lib partagée ; build depuis la racine)
└── tests/              # tests du waf-exporter (parseur, métrique exposée, suivi du journal) + contrat de configuration
```

## Image et build

| Point | Choix |
|---|---|
| Base | `owasp/modsecurity-crs:4.25.2-nginx-alpine-lts` (ModSecurity v3 + OWASP CRS préinstallés, configurés par l'entrypoint de l'image : `BLOCKING_PARANOIA=1`, `ANOMALY_INBOUND=5`, `ANOMALY_OUTBOUND=4`, `ALLOWED_METHODS="GET HEAD POST OPTIONS DELETE PATCH"` — DELETE pour les bénéficiaires #43, PATCH pour les réglages de carte #47, refusés en 405 par `$method_denied` sur tout autre chemin ; PUT refusé) |
| Utilisateur | **non-root** (`nginx`, image *unprivileged*) → écoute **8080 / 8443** ; Compose publie `80:8080` et `443:8443` (seul service avec `ports:`) |
| TLS | certificat **auto-signé généré au build** (`openssl req -x509`, ECDSA P-256, SAN `localhost`/`waf`/`192.168.137.1`) dans `/etc/nginx/conf/` — jamais commité ; les clients de labo utilisent `-k` / contexte non vérifié |
| Config | `nginx.conf` du projet copié tel quel (les templates `nginx.conf`/`conf.d` de l'image sont retirés) ; les templates `modsecurity.d` de l'image restent et rendent `/etc/modsecurity.d/setup.conf` au démarrage |
| Upstreams | `front:8080` (le conteneur front est lui aussi non-root sur 8080), `payment-api:8001`, `auth:8002` |
| Sonde | `GET /healthz` servi par le WAF (sans upstream) ; healthcheck image + Compose `curl -fsk https://127.0.0.1:8443/healthz` |
| Logs | access log JSON `json_waf` sur **stdout** → Promtail/Loki ; audit ModSecurity (JSON Serial, blocages 4xx/5xx) dans `/var/log/modsec/audit.json` (volume `waf-logs`) → `waf-exporter` |

```bash
docker compose -f infra/compose/docker-compose.yml build waf
curl -k https://localhost/healthz                      # ok
curl -k "https://localhost/?q=<script>alert(1)</script>"   # 403 (CRS)
```

## Interface de blocage IP (consommée par la remédiation)

L'action `waf_block_ip` / `waf_blacklist_ip` du moteur de remédiation (aucun `docker exec`, aucun accès hôte) :

1. le playbook `infra/ansible/playbooks/remediation/waf_deny_ip.yml`, exécuté **dans le conteneur remediation**, ajoute une ligne `"<ip> 1;"` (idempotent, `lineinfile`) dans `/etc/nginx/deny/blocked_ips.conf` — un **volume Compose `waf-deny`** monté dans les deux conteneurs (WAF : `/etc/nginx/deny`, remediation : `/etc/resilience/waf-deny`) ;
2. si la liste a changé, le moteur envoie **SIGHUP** au conteneur `waf` via le docker-socket-proxy (`POST /containers/{id}/kill?signal=HUP`, seul signal autorisé) = `nginx -s reload`.

Droits : le répertoire est `nginx:nginx`, `2775` (setgid) ; le moteur (uid 10001) rejoint le groupe `101` (`group_add`) pour y écrire, nginx relit le fichier (0644) au reload. Les requêtes des IP listées reçoivent **403**. Interface stable — ne pas changer le format sans mettre à jour `remediation/` et `docs/contracts.md`. Remise à zéro : `attacks/reset.sh` (vide le fichier via `docker compose exec waf` puis reload).

## Observabilité (fonction SOC) — `waf-exporter` (ticket #12)

- `nginx.conf` émet un access log **JSON** (`json_waf`) récupéré par Promtail → Loki.
- Le WAF écrit l'**audit log ModSecurity** (variables de l'image CRS : `MODSEC_AUDIT_LOG_FORMAT=JSON`,
  `MODSEC_AUDIT_LOG_TYPE=Serial`, `MODSEC_AUDIT_ENGINE=RelevantOnly`) dans `/var/log/modsec/audit.json`,
  sur le volume Compose **`waf-logs`**.
- Le service **`waf-exporter`** (`waf_exporter.py`, `Dockerfile.exporter`) monte ce volume en **lecture seule**,
  suit le fichier (`tail -F` : attente du fichier, ajouts, troncature) et, pour chaque transaction
  **403 avec une règle CRS** :
  - incrémente `resilience_waf_blocked_total{rule}` — exposée sur `GET /metrics` **:9188**, réseau `obs`
    uniquement (cible Prometheus `waf-exporter:9188`, job `waf-exporter`) ;
  - émet un log JSON `waf_blocked` (contrat §1 : `client_ip`, `http_path`, `http_status`) sur stdout.
- Consommateurs : feature ML `waf_blocked_per_s` = `sum(rate(resilience_waf_blocked_total[W]))` (signal
  dominant de `web_attack`) et règle SOC `soc-waf-blocks`.
- Au (re)démarrage l'exporteur part de la **fin** du fichier (pas de recomptage) ; `--from-start` pour tout relire.
- Droits : répertoire `nginx:nginx 0755` créé au build ; l'exporteur (uid 10006) rejoint le groupe `101` en secours.

```bash
# En stack : une requête bloquée par le CRS doit faire monter le compteur
curl -k "https://localhost/?q=<script>alert(1)</script>"      # 403
docker compose -f infra/compose/docker-compose.yml exec waf-exporter \
  python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9188/metrics').read().decode())" \
  | grep resilience_waf_blocked_total
```

## Lancement / test

```bash
# waf-exporter (parseur, métrique exposée au format Prometheus, suivi du journal) + contrat de configuration
# (upstream front:8080, non-root, TLS, routes, compose, câblage waf-exporter/Prometheus, méthodes CRS + DELETE/PATCH restreints) : 33 tests, sans conteneur
python -m pytest security/waf/tests/ -q
```

Le WAF est déclaré dans `infra/compose/docker-compose.yml` sur `edge` + `app` ; c'est le seul service publiant des ports HTTP. Le profil `iot` publie en plus MQTT sur l'interface du PA.
La validation complète (build des images, blocage CRS effectif → `resilience_waf_blocked_total` qui monte dans Prometheus, parcours login → virement via le WAF) se fait stack levée (`make up`).
