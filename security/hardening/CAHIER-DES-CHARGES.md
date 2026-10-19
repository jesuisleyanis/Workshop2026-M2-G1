# Cahier des charges — Durcissement (security/hardening/)

## Rôle et exigences couvertes

Durcissement des composants et des accès sur l'ensemble de la plateforme. Couvre :
- **R14** — durcissement des composants et des accès, privilèges maîtrisés.
- **R15** (transverse) — modèle de privilèges du moteur de remédiation.

## Périmètre

- `hardening.md` — checklist appliquée à chaque conteneur (image slim, non-root, `cap_drop: ALL`, `no-new-privileges`, `read_only`, limites CPU/RAM, healthcheck, réseaux internes).
- `audit.sh` — audit automatisé du dépôt (exit 0/1, réutilisable par la future CI) :
  1. aucun montage direct du socket Docker (hors docker-socket-proxy) ;
  2. aucun conteneur `privileged: true` ;
  3. aucun secret en clair ;
  4. aucune clé age dans le dépôt.
- Documentation de `trivy` (scan d'images) et `gitleaks` (pre-commit).

Hors périmètre : benchmarks CIS complets, durcissement de l'OS hôte (délégué au PC Hôte / coach).

## Contraintes

- Le moteur de remédiation **n'accède jamais** au socket Docker brut (médiation par `docker-socket-proxy`).
- Seul le WAF publie des ports.
- Aucun secret en image ; injection au runtime via SOPS.

## Critères d'acceptation

- [ ] `audit.sh` renvoie 0 sur un dépôt conforme et 1 dès qu'une règle est violée.
- [ ] Chaque `Dockerfile` : base slim, `USER` non-root, `HEALTHCHECK`.
- [ ] Chaque service applicatif dans `docker-compose.yml` : `cap_drop: ALL`, `no-new-privileges`, limites mémoire.
- [ ] `trivy` et `gitleaks` documentés avec leur commande.

## Vérification

```bash
security/hardening/audit.sh      # audit complet du dépôt (0 = conforme)
```
