#!/usr/bin/env bash
# Remet la cible à l'état "avant" : arrête les scénarios, re-seed, redéploie.
# Idempotent : peut être relancé sans effet de bord.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== reset du banc d'essai =="
"${ROOT}/attacks/run.sh" --stop || true

# Vide la liste de blocage IP du WAF. Remplacement par renommage (comme le moteur) et non
# troncature : le fichier appartient à l'uid du moteur de remédiation (écrit en 0644), seul
# le dossier est inscriptible pour l'hôte. Le WAF détecte le changement et se recharge seul.
BLOCKLIST="${ROOT}/security/waf/blocklist/blocked_ips.conf"
echo "# vidé par attacks/reset.sh" > "${BLOCKLIST}.tmp"
mv -f "${BLOCKLIST}.tmp" "${BLOCKLIST}"

# Re-seed des données fictives + redéploiement (délégués au Makefile racine).
if command -v make >/dev/null 2>&1; then
  make -C "${ROOT}" seed || echo "(seed : à lancer manuellement si la stack n'est pas up)"
fi

echo "== reset terminé : état 'avant' rétabli =="
