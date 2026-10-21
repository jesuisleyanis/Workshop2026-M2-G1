# Cahier des charges — WAF (security/waf/)

## Rôle et exigences couvertes

Pare-feu applicatif en frontal, **seul point d'entrée HTTP** de la plateforme. Le broker MQTT du profil `iot` est publié séparément sur le PA. Couvre :
- **R11** — filtrage applicatif par WAF (Nginx + ModSecurity + OWASP CRS).
- **R19** — publication réseau maîtrisée : seuls 80/443 sont exposés sur le hotspot.

## Périmètre

- Reverse-proxy vers le front (statique) et les API métier (`/api/v1/...`).
- ModSecurity + jeu de règles OWASP CRS actifs.
- TLS auto-signé généré au build de l'image (environnement de labo fermé).
- Image officielle OWASP CRS (nginx *unprivileged*, non-root) : écoute 8080/8443, publiée 80/443 par Compose.
- **Liste de blocage IP rechargeable à chaud** (`deny/blocked_ips.conf`, volume partagé `waf-deny`), pilotée par le moteur de remédiation (écriture par playbook, reload par SIGHUP via le docker-socket-proxy).
- **`waf-exporter`** (`waf_exporter.py`, conteneur dédié `Dockerfile.exporter`) : suit l'audit log ModSecurity (JSON, volume partagé `waf-logs`) et transforme chaque blocage en métrique `resilience_waf_blocked_total{rule}` (`/metrics` :9188, réseau `obs`) et en log event `waf_blocked` (contrat §1).

Hors périmètre : terminaison TLS de production, gestion de certificats signés, répartition de charge.

## Interfaces (voir docs/contracts.md)

| Interface | Direction | Détail |
|---|---|---|
| HTTP 80/443 | entrée | Seul point exposé ; transmet `X-Forwarded-For` |
| `deny/blocked_ips.conf` (volume `waf-deny`) | entrée (remédiation) | `waf_block_ip`/`waf_blacklist_ip` ajoutent `"<ip> 1;"` (playbook in-container) puis SIGHUP au conteneur = `nginx -s reload` |
| access log JSON `json_waf` | sortie | Récupéré par Promtail → Loki (fonction SOC) |
| audit log ModSecurity (volume `waf-logs`) | sortie (interne) | JSON Serial, blocages 4xx/5xx ; lu en lecture seule par `waf-exporter` |
| `resilience_waf_blocked_total{rule}` | sortie | Métrique §2 exposée par `waf-exporter` (:9188, `obs`), scrappée par Prometheus ; alimente `waf_blocked_per_s` du vecteur ML et la règle SOC `soc-waf-blocks` |

## Contraintes de sécurité

- **Ne route jamais** les endpoints internes (`/internal/*`, `/metrics` des services, remédiation).
- En-têtes de sécurité (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
- Conteneur durci (voir `security/hardening/`).

## Critères d'acceptation

- [ ] Une requête légitime vers le front et `/api/v1/*` est relayée (200).
- [ ] Une charge typée injection/traversal est bloquée par le CRS (403) et comptée.
- [ ] Une IP ajoutée à `deny/blocked_ips.conf` + reload (SIGHUP) reçoit 403.
- [ ] Les blocages apparaissent en métrique et en log `waf_blocked`.
- [ ] Aucun service interne n'est joignable depuis le hotspot (vérifié par `docs/network.md`).

## Tests

`python -m pytest security/waf/tests/ -q` — exporteur (parsing des blocages ModSecurity → métrique exposée, suivi du journal d'audit) + contrat de configuration Dockerfile / nginx.conf / compose (upstream `front:8080`, non-root, TLS au build, routes publiques seules — dont `/api/v1/status` limitée par IP (#42) et `/api/v1/beneficiaries` (#43, limitée par IP) —, méthodes CRS autorisées et `DELETE` restreint à `/api/v1/beneficiaries/<id>`, healthcheck) : **29 tests**. La validation du proxy complet se fait avec la stack levée.
