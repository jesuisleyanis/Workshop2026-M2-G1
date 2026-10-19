# WAF — Nginx + ModSecurity + OWASP CRS

> Couvre **R11** (filtrage applicatif, seul point exposé) et **R19** (publication réseau maîtrisée).

## Rôle

Reverse-proxy unique en frontal de la plateforme. **Seul composant exposé** sur le hotspot (80/443, TLS auto-signé). Protège le front et les API métier via ModSecurity + le jeu de règles OWASP CRS, et porte la **liste de blocage IP** pilotée par la remédiation.

## Arborescence

```
security/waf/
├── nginx.conf          # reverse-proxy + ModSecurity + liste de blocage
├── blocked_ips.conf    # liste de deny rechargeable (gérée par la remédiation)
├── waf_exporter.py     # logs de blocage -> métrique resilience_waf_blocked_total + event waf_blocked
├── tls/                # certificat auto-signé (généré au build, non commité)
└── tests/              # tests du waf-exporter
```

## Interface de blocage IP (consommée par la remédiation)

L'action `waf_block_ip` / `waf_blacklist_ip` du moteur de remédiation :

1. ajoute une ligne `"<ip> 1;"` dans `security/waf/blocked_ips.conf` (monté dans le conteneur) ;
2. déclenche un rechargement à chaud : `docker exec waf nginx -s reload` (ou via le playbook Ansible `waf_deny_ip.yml`).

Les requêtes des IP listées reçoivent **403**. Interface stable — ne pas changer le format sans mettre à jour `remediation/` et `docs/contracts.md`.

## Observabilité (fonction SOC)

- `nginx.conf` émet un access log **JSON** (`json_waf`) récupéré par Promtail → Loki.
- `waf_exporter.py` transforme les blocages ModSecurity en métrique `resilience_waf_blocked_total{rule}` et en event log `waf_blocked` (contrat §1), qui alimentent les règles d'alerte SOC et le vecteur de features ML (`waf_blocked_per_s`).

## Lancement / test

```bash
# Test unitaire du parseur (sans conteneur)
python -m pytest security/waf/tests/ -q

# Génération du certificat auto-signé (fait au build de l'image WAF)
openssl req -x509 -newkey rsa:2048 -nodes -days 7 \
  -keyout tls/server.key -out tls/server.crt -subj "/CN=resilience-g1"
```

Le WAF est déclaré dans `infra/compose/docker-compose.yml` sur le réseau `edge` (seul service publiant des ports) + `app`.
