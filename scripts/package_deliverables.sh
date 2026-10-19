#!/usr/bin/env bash
# Assemble l'archive Code.zip du rendu (§7.4) — SANS aucun secret en clair.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODE="Workshop2026-M2-G1-Code.zip"

cd "${ROOT}"

echo "== Vérification sécurité avant packaging =="
security/hardening/audit.sh

echo "== Construction de ${CODE} =="
rm -f "${CODE}"
# Exclut .git, secrets déchiffrés, clés, artefacts, dépendances.
zip -r "${CODE}" . \
  -x '.git/*' \
  -x '*/node_modules/*' \
  -x '*/.venv/*' '*/venv/*' \
  -x '*/__pycache__/*' '*.pyc' \
  -x '.env' '*.decrypted.env' \
  -x '**/keys.txt' '**/*.age' \
  -x '**/chroma/*' '*.joblib' \
  -x '**/incidents.db' '*.sqlite3' \
  -x "${CODE}" \
  >/dev/null

echo "== Contrôle : aucun secret déchiffré dans l'archive =="
if unzip -l "${CODE}" | grep -E '\.env$|keys\.txt|\.age$'; then
  echo "ERREUR : secret potentiel dans l'archive — abandon." >&2
  rm -f "${CODE}"
  exit 1
fi

echo "OK — ${CODE} prêt ($(du -h "${CODE}" | cut -f1))."
echo "Rappel : fournir la clé age de démo HORS archive pour permettre le déploiement."
