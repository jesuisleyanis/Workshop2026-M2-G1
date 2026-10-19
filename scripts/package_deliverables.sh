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
  -x '*/node_modules/*' '*/dist/*' '*/.vite/*' '*/coverage/*' \
  -x '*/.venv/*' '*/venv/*' \
  -x '*/__pycache__/*' '*.pyc' \
  -x '.env' '*.decrypted.env' \
  -x '**/keys.txt' '**/*.age' \
  -x '**/chroma/*' '*.joblib' \
  -x '**/incidents.db' '*.sqlite3' \
  -x '*.egg-info/*' '*/.pytest_cache/*' '.pytest_cache/*' '*/.ruff_cache/*' '.ruff_cache/*' '*/.mypy_cache/*' '.mypy_cache/*' \
  -x 'infra/ansible/backups/*' \
  -x 'attacks/.runlog' 'attacks/.run.pid' \
  -x 'Workshop2026-M2-G1-*' \
  >/dev/null

echo "== Contrôle : aucun secret déchiffré dans l'archive =="
# Noms de fichiers interdits (secrets déchiffrés, clés) ; les fichiers SOPS chiffrés (*.enc.*) sont attendus.
if unzip -l "${CODE}" | awk '{print $4}' | grep -E '(^|/)\.env$|\.decrypted\.env$|keys\.txt$|\.age$|(^|/)age\.key$'; then
  echo "ERREUR : secret potentiel dans l'archive — abandon." >&2
  rm -f "${CODE}"
  exit 1
fi
# Contenu : aucune clé privée age ni clé SSH privée dans l'archive (motif découpé pour ne pas s'auto-détecter).
if unzip -p "${CODE}" 2>/dev/null | grep -aE 'AGE-SECRET-KEY-[1]|BEGIN (RSA |OPENSSH |EC )?PRIVATE KE[Y]' | grep -q .; then
  echo "ERREUR : clé privée détectée dans le contenu de l'archive — abandon." >&2
  rm -f "${CODE}"
  exit 1
fi

echo "OK — ${CODE} prêt ($(du -h "${CODE}" | cut -f1))."
echo "Rappel : fournir la clé age de démo HORS archive pour permettre le déploiement."
