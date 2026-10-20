#!/usr/bin/env bash
# Remet la cible à l'état "avant" : arrête les scénarios, re-seed, redéploie.
# Idempotent : peut être relancé sans effet de bord.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== reset du banc d'essai =="
"${ROOT}/attacks/run.sh" --stop || true

# Vide la liste de blocage IP du WAF.
: > "${ROOT}/security/waf/blocklist/blocked_ips.conf"
echo "# vidé par attacks/reset.sh" >> "${ROOT}/security/waf/blocklist/blocked_ips.conf"

# Re-seed des données fictives + redéploiement (délégués au Makefile racine).
if command -v make >/dev/null 2>&1; then
  make -C "${ROOT}" seed || echo "(seed : à lancer manuellement si la stack n'est pas up)"
fi

echo "== reset terminé : état 'avant' rétabli =="
