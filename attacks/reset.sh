#!/usr/bin/env bash
# Remet la cible à l'état "avant" : arrête les scénarios, re-seed, redéploie.
# Idempotent : peut être relancé sans effet de bord.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== reset du banc d'essai =="
"${ROOT}/attacks/run.sh" --stop || true

# Vide la deny-list IP du WAF (volume partagé `waf-deny`) et recharge Nginx à chaud.
COMPOSE=(docker compose -f "${ROOT}/infra/compose/docker-compose.yml")
# .env de la racine (make decrypt) : sans lui, Compose échoue sur les ${VAR:?} du fichier.
if [[ -f "${ROOT}/.env" ]]; then COMPOSE+=(--env-file "${ROOT}/.env"); fi
if "${COMPOSE[@]}" ps --status running waf >/dev/null 2>&1; then
  "${COMPOSE[@]}" exec -T waf sh -c \
    'printf "# vidé par attacks/reset.sh\n" > /etc/nginx/deny/blocked_ips.conf && nginx -s reload' \
    || echo "(deny-list : WAF non joignable, à vider manuellement)"
fi

# Annule une éventuelle corruption data_corruption (renommage inverse, idempotent).
# Inventaire OBLIGATOIRE (#14) : sans `-i`, le groupe [host] est vide et la play est un no-op
# silencieux. Sortie visible et échec PROPAGÉ (set -e) : plus de `|| echo` qui avale une erreur.
# Ne s'applique que si la base tourne ; sinon on le dit et on passe (reset idempotent hors stack).
if "${COMPOSE[@]}" ps --status running postgres 2>/dev/null | grep -q postgres; then
  if command -v ansible-playbook >/dev/null 2>&1; then
    ansible-playbook -i "${ROOT}/infra/ansible/inventory/hosts.ini" \
      "${ROOT}/infra/ansible/playbooks/db_corrupt_fake.yml" -e mode=revert
  else
    echo "ansible-playbook introuvable : revert data_corruption impossible" >&2
    exit 1
  fi
else
  echo "(revert data_corruption : base non démarrée, rien à annuler)"
fi

# Re-seed des données fictives + redéploiement (délégués au Makefile racine).
if command -v make >/dev/null 2>&1; then
  make -C "${ROOT}" seed || echo "(seed : à lancer manuellement si la stack n'est pas up)"
fi

echo "== reset terminé : état 'avant' rétabli =="
