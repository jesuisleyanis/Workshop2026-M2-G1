# Cahier des charges — WAF (security/waf/)

## Rôle et exigences couvertes

Pare-feu applicatif en frontal, **seul point exposé** de la plateforme. Couvre :
- **R11** — filtrage applicatif par WAF (Nginx + ModSecurity + OWASP CRS).
- **R19** — publication réseau maîtrisée : seuls 80/443 sont exposés sur le hotspot.

## Périmètre

- Reverse-proxy vers le front (statique) et les API métier (`/api/v1/...`).
- ModSecurity + jeu de règles OWASP CRS actifs.
- TLS auto-signé (environnement de labo fermé), généré au premier démarrage par l'image OWASP CRS.
- Image `owasp/modsecurity-crs` **épinglée** (CRS 4 LTS), non-root, ports internes 8080/8443.
- **Liste de blocage IP rechargeable à chaud** (`blocklist/blocked_ips.conf`, dossier monté en lecture seule), pilotée par le moteur de remédiation.
- `waf_exporter.py` (service compose `waf-exporter`) : suit le journal d'audit ModSecurity et transforme les blocages en métrique `resilience_waf_blocked_total{rule}` et en log event `waf_blocked` (contrat §1).

Hors périmètre : terminaison TLS de production, gestion de certificats signés, répartition de charge.

## Interfaces (voir docs/contracts.md)

| Interface | Direction | Détail |
|---|---|---|
| HTTP 80/443 | entrée | Seul point exposé ; transmet `X-Forwarded-For` |
| `blocklist/blocked_ips.conf` | entrée (remédiation) | `waf_block_ip`/`waf_blacklist_ip` (extravars `deny_ip`, `deny_list`, `incident_id`) ajoutent `"<ip> 1;"` puis `nginx -s reload` |
| access log JSON `json_waf` | sortie | Récupéré par Promtail → Loki (fonction SOC) |
| `resilience_waf_blocked_total{rule}` | sortie | Métrique §2 (`waf-exporter:9188`), alimente `waf_blocked_per_s` du vecteur ML |
| journal d'audit ModSecurity JSON | sortie (volume tmpfs `waf-logs`) | Lu en lecture seule par waf-exporter ; parties `AHZ`, 403 seulement |

## Contraintes de sécurité

- **Ne route jamais** les endpoints internes (`/internal/*`, `/metrics` des services, remédiation).
- En-têtes de sécurité (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
- Conteneur durci (voir `security/hardening/`) : non-root, `cap_drop: ALL`, `no-new-privileges`, limite mémoire.
- Rien de secret dans ce qui part vers Loki (access log sans query ni corps, `error_log` à `error` **masqué par Promtail**
  — query strings, `[data]`, `(Value: …)` —, event `waf_blocked` sans query). Le journal d'audit (seuls les 403, parties
  `AHZ`) peut contenir la donnée appariée par une règle : tmpfs borné **et tronqué au seuil**, `0750`, lu du seul
  waf-exporter (risque résiduel documenté dans le README).
- `error_log` à `error` : les causes des 502 restent diagnostiquables.
- `X-Forwarded-For` écrasé (pas d'usurpation d'IP source).

## Critères d'acceptation

- [x] Une requête légitime vers le front est relayée (200, HTTP et HTTPS).
- [ ] Une requête légitime vers `/api/v1/*` est relayée **et répond 200** (critère d'origine, non affaibli). Aujourd'hui le
  WAF route bien (testé contre des backends factices) mais, sur cette branche, payment-api/auth ne démarrent pas
  (ROADMAP I12, corrigé sur `fix/stack-startup`) : on obtient 502. À cocher une fois la stack complète levée.
- [x] Une charge typée injection est bloquée par le CRS (SQLi 403 règle 942100, XSS 403 règle 941100) et comptée ;
  la traversée de chemin est refusée (400) par Nginx avant le CRS.
- [x] Une IP écrite **par renommage** dans `blocklist/blocked_ips.conf` (comme `lineinfile`) + reload reçoit 403 ; retirée + reload, 200 (testé sur la vraie image, `test_waf_image.py`).
- [x] Aucun secret dans Loki : mot de passe et jeton piégés absents des logs du WAF et de waf-exporter (vérifié).
- [x] Les blocages apparaissent en métrique (`resilience_waf_blocked_total{rule}` dans Prometheus, `rate()` > 0) et en
  log `waf_blocked` (waf-exporter).
- [x] Seul le WAF publie des ports (`80->8080`, `443->8443`) ; `/metrics`, `/internal/*` et toute route `/api/` non
  déclarée renvoient 404 au niveau du WAF, sans atteindre un backend (testé).
- [x] Le journal d'audit ne peut pas remplir son tmpfs : tronqué au seuil, nginx continue d'écrire, waf-exporter relit
  depuis le début (testé).
- [ ] **Chaîne `web_attack` de bout en bout** (attaque → détection → `waf_block_ip` → IP bloquée → `verify_tx` OK) : bloquée
  par ROADMAP **I11** (reload via `docker-socket-proxy`, `source_ip` du detector). Le WAF n'est pas ✅ au ROADMAP tant que
  `RESILIENCE_E2E=1 pytest tests/e2e -k web_attack` n'est pas vert.

## Tests

| Commande | Ce qui est vérifié |
|---|---|
| `python -m pytest security/waf/tests/ -q` | **Sans conteneur.** waf-exporter (parsing, métrique, suivi du journal, troncature/rotation) ; **garanties de sécurité des modèles** (`test_nginx_conf.py`) : routes internes en 404, backends déclarés seuls, `X-Forwarded-For` écrasé, 403 avant tout proxy, en-têtes, montage **dossier** en lecture seule aligné sur l'`include`, variables du playbook alignées sur le moteur, seul le WAF publie des ports, niveau d'`error_log`, masquage Promtail, script de rotation |
| `make test-waf` (Docker) | **Vraie image** `nginx -t`, CRS (SQLi 403 + journal), blocage par renommage + reload, XFF usurpé, 404 sans backend, troncature du journal, cause d'un 502 dans `error_log` — `test_waf_image.py` |
| `RESILIENCE_E2E=1 pytest tests/e2e -k web_attack` | Chaîne complète, stack levée — **à rejouer** quand I11 est levé |
