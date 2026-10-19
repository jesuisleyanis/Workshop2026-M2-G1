# Cahier des charges — WAF (security/waf/)

## Rôle et exigences couvertes

Pare-feu applicatif en frontal, **seul point exposé** de la plateforme. Couvre :
- **R11** — filtrage applicatif par WAF (Nginx + ModSecurity + OWASP CRS).
- **R19** — publication réseau maîtrisée : seuls 80/443 sont exposés sur le hotspot.

## Périmètre

- Reverse-proxy vers le front (statique) et les API métier (`/api/v1/...`).
- ModSecurity + jeu de règles OWASP CRS actifs.
- TLS auto-signé généré au build de l'image (environnement de labo fermé).
- Image officielle OWASP CRS (nginx *unprivileged*, non-root) : écoute 8080/8443, publiée 80/443 par Compose.
- **Liste de blocage IP rechargeable à chaud** (`blocked_ips.conf`), pilotée par le moteur de remédiation.
- `waf_exporter.py` : transforme les blocages ModSecurity en métrique `resilience_waf_blocked_total{rule}` et en log event `waf_blocked` (contrat §1).

Hors périmètre : terminaison TLS de production, gestion de certificats signés, répartition de charge.

## Interfaces (voir docs/contracts.md)

| Interface | Direction | Détail |
|---|---|---|
| HTTP 80/443 | entrée | Seul point exposé ; transmet `X-Forwarded-For` |
| `blocked_ips.conf` | entrée (remédiation) | `waf_block_ip`/`waf_blacklist_ip` ajoutent `"<ip> 1;"` puis `nginx -s reload` |
| access log JSON `json_waf` | sortie | Récupéré par Promtail → Loki (fonction SOC) |
| `resilience_waf_blocked_total{rule}` | sortie | Métrique §2, alimente `waf_blocked_per_s` du vecteur ML |

## Contraintes de sécurité

- **Ne route jamais** les endpoints internes (`/internal/*`, `/metrics` des services, remédiation).
- En-têtes de sécurité (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
- Conteneur durci (voir `security/hardening/`).

## Critères d'acceptation

- [ ] Une requête légitime vers le front et `/api/v1/*` est relayée (200).
- [ ] Une charge typée injection/traversal est bloquée par le CRS (403) et comptée.
- [ ] Une IP ajoutée à `blocked_ips.conf` + reload reçoit 403.
- [ ] Les blocages apparaissent en métrique et en log `waf_blocked`.
- [ ] Aucun service interne n'est joignable depuis le hotspot (vérifié par `docs/network.md`).

## Tests

`python -m pytest security/waf/tests/ -q` — parsing des blocages ModSecurity → métrique/event (5 tests) + contrat de configuration Dockerfile / nginx.conf / compose (9 tests : upstream `front:8080`, non-root, TLS au build, routes publiques seules, healthcheck). La validation du proxy complet se fait avec la stack levée.
