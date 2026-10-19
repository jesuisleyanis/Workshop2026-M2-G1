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
- **Liste de blocage IP rechargeable à chaud** (`blocked_ips.conf`), pilotée par le moteur de remédiation.
- `waf_exporter.py` (service compose `waf-exporter`) : suit le journal d'audit ModSecurity et transforme les blocages en métrique `resilience_waf_blocked_total{rule}` et en log event `waf_blocked` (contrat §1).

Hors périmètre : terminaison TLS de production, gestion de certificats signés, répartition de charge.

## Interfaces (voir docs/contracts.md)

| Interface | Direction | Détail |
|---|---|---|
| HTTP 80/443 | entrée | Seul point exposé ; transmet `X-Forwarded-For` |
| `blocked_ips.conf` | entrée (remédiation) | `waf_block_ip`/`waf_blacklist_ip` ajoutent `"<ip> 1;"` puis `nginx -s reload` |
| access log JSON `json_waf` | sortie | Récupéré par Promtail → Loki (fonction SOC) |
| `resilience_waf_blocked_total{rule}` | sortie | Métrique §2 (`waf-exporter:9188`), alimente `waf_blocked_per_s` du vecteur ML |
| journal d'audit ModSecurity JSON | sortie (volume tmpfs `waf-logs`) | Lu en lecture seule par waf-exporter ; parties `AHZ`, 403 seulement |

## Contraintes de sécurité

- **Ne route jamais** les endpoints internes (`/internal/*`, `/metrics` des services, remédiation).
- En-têtes de sécurité (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
- Conteneur durci (voir `security/hardening/`) : non-root, `cap_drop: ALL`, `no-new-privileges`, limite mémoire.
- Rien de secret dans ce qui part vers Loki (access log sans query ni corps, `error_log` à `crit`, event `waf_blocked`
  sans query). Le journal d'audit (seuls les 403, parties `AHZ`) peut contenir la donnée appariée par une règle : tmpfs
  borné, `0750`, lu du seul waf-exporter (risque résiduel documenté dans le README).
- `X-Forwarded-For` écrasé (pas d'usurpation d'IP source).

## Critères d'acceptation

- [x] Une requête légitime vers le front est relayée (200, HTTP et HTTPS). `/api/v1/*` est routé (502 tant que
  payment-api/auth ne démarrent pas — hors WAF, voir ROADMAP).
- [x] Une charge typée injection est bloquée par le CRS (SQLi 403 règle 942100, XSS 403 règle 941100) et comptée ;
  la traversée de chemin est refusée (400) par Nginx avant le CRS.
- [x] Une IP ajoutée à `blocked_ips.conf` + reload reçoit 403 ; retirée + reload, 200.
- [x] Aucun secret dans Loki : mot de passe et jeton piégés absents des logs du WAF et de waf-exporter (vérifié).
- [x] Les blocages apparaissent en métrique (`resilience_waf_blocked_total{rule}` dans Prometheus, `rate()` > 0) et en
  log `waf_blocked` (waf-exporter).
- [x] Seul le WAF publie des ports (`80->8080`, `443->8443`) ; `/metrics`, `/internal/*` et toute route `/api/` non
  déclarée renvoient 404 au niveau du WAF.

## Tests

`python -m pytest security/waf/tests/ -q` — parsing des blocages ModSecurity → métrique/event (5 tests). La validation du proxy complet se fait avec la stack levée.
