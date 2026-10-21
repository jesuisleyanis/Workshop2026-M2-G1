#!/usr/bin/env bash
# Remet la cible à l'état "avant" : arrête les scénarios, re-seed, redéploie.
# Idempotent : peut être relancé sans effet de bord.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== reset du banc d'essai =="
"${ROOT}/attacks/run.sh" --stop || true

# Vide la deny-list IP du WAF (volume partagé `waf-deny`) et recharge Nginx à chaud.
COMPOSE=(docker compose -f "${ROOT}/infra/compose/docker-compose.yml")
# Sans --env-file, Compose cherche infra/compose/.env (absent) : l'interpolation échoue (variables
# requises), `ps` aussi, et la deny-list n'était JAMAIS vidée.
[[ -f "${ROOT}/.env" ]] && COMPOSE+=(--env-file "${ROOT}/.env")
if "${COMPOSE[@]}" ps --status running waf >/dev/null 2>&1; then
  # Le fichier appartient à la remédiation (volume waf-deny) : écrit depuis son conteneur, relu par le WAF.
  { "${COMPOSE[@]}" exec -T remediation sh -c \
      'echo "# vidé par attacks/reset.sh" > /etc/resilience/waf-deny/blocked_ips.conf' \
    && "${COMPOSE[@]}" exec -T waf nginx -s reload 2>/dev/null; } \
    || echo "(deny-list : remédiation/WAF non joignables, lancer make unblock)"
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
