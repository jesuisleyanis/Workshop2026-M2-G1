#!/usr/bin/env bash
# Exporte le dossier (§7.1) : dossier.md -> dossier.html -> Workshop2026-M2-G1-Dossier.pdf (racine du dépôt).
# Dépendances : python avec le paquet `markdown` (pip install markdown) ; Google Chrome ou Chromium (headless).
# Usage : docs/dossier/build.sh [--html-only]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"
PY="${PYTHON:-python3}"
OUT="${ROOT}/Workshop2026-M2-G1-Dossier.pdf"
HTML="${HERE}/dossier.html"

"${PY}" - "${HERE}/dossier.md" "${HERE}/style.css" "${HTML}" <<'PYEOF'
import sys
from pathlib import Path
import markdown  # pip install markdown

src, css, out = (Path(p) for p in sys.argv[1:4])
body = markdown.markdown(src.read_text(encoding="utf-8"),
                         extensions=["tables", "fenced_code", "md_in_html", "attr_list"])
html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>PROJECT RESILIENCE-ALPHA — Dossier G1</title>
<style>{css.read_text(encoding="utf-8")}</style></head><body>{body}</body></html>"""
out.write_text(html, encoding="utf-8")
print(f"HTML : {out}")
PYEOF

if [[ "${1:-}" == "--html-only" ]]; then exit 0; fi

CHROME="$(command -v google-chrome || command -v chromium || command -v chromium-browser || command -v chrome || true)"
[[ -n "${CHROME}" ]] || { echo "Chrome/Chromium introuvable : ouvrir ${HTML} et imprimer en PDF (A4, sans en-têtes)." >&2; exit 1; }

"${CHROME}" --headless=new --no-sandbox --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="${OUT}" "file://${HTML}" >/dev/null 2>&1
echo "PDF  : ${OUT}"
if command -v pdfinfo >/dev/null 2>&1; then
  pages="$(pdfinfo "${OUT}" | awk '/^Pages:/{print $2}')"
  echo "Pages : ${pages} (cible : 8 à 12 hors annexes, page de garde comprise ici)"
fi
