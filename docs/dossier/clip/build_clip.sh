#!/usr/bin/env bash
# build_clip.sh — assemble le Clip Chrono (<= 60 s, SANS coupe) a partir d'UNE prise ecran continue.
#
# Le clip est un enregistrement de la demo reelle (voir README.md) : ce script ne fabrique pas
# d'images, il recadre la prise brute au budget de temps et incruste les legendes du storyboard.
# Il n'insere AUCUNE coupe : une seule entree video, filtre de dessin uniquement (contrainte sujet §7).
#
# Usage : build_clip.sh <prise_brute> [t_debut]
#   <prise_brute>  enregistrement continu (mkv/mp4...) demarrant au plus tard au temps "AVANT".
#   [t_debut]      decalage (s ou hh:mm:ss) du top "AVANT" dans la prise (defaut 0).
#
# Sortie : ../../../Workshop2026-M2-G1-VidChrono.mp4 (a la racine du depot, ignore par git).
# Prerequis : ffmpeg + ffprobe, et python3 (present sur le poste de demo : toute la stack est Python).
set -euo pipefail
export PYTHONUTF8=1   # lecture du storyboard (accents) independante de la locale

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/../../.." && pwd)"
JSON="${HERE}/storyboard.json"
OUT="${ROOT}/Workshop2026-M2-G1-VidChrono.mp4"

RAW="${1:-}"
START="${2:-0}"
if [[ -z "${RAW}" || ! -f "${RAW}" ]]; then
  echo "Usage : $0 <prise_brute.mkv> [t_debut]   (prise brute introuvable)" >&2
  exit 2
fi
# t_debut : secondes (12 / 12.5) ou horodatage (mm:ss / hh:mm:ss). Evite une erreur ffmpeg obscure.
if ! [[ "${START}" =~ ^[0-9]+(\.[0-9]+)?$ || "${START}" =~ ^([0-9]+:){1,2}[0-9]+(\.[0-9]+)?$ ]]; then
  echo "t_debut invalide : '${START}' (attendu secondes ou [hh:]mm:ss)" >&2
  exit 2
fi
command -v ffmpeg  >/dev/null || { echo "ffmpeg manquant" >&2; exit 3; }
command -v ffprobe >/dev/null || { echo "ffprobe manquant" >&2; exit 3; }
command -v python3 >/dev/null || { echo "python3 manquant (generation des legendes)" >&2; exit 3; }

# Budget max (borne dure du livrable) et duree utile (fin du dernier segment) lus depuis le contrat.
BUDGET="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1],encoding="utf-8"))["budget_seconds_max"])' "${JSON}")"
DUR="$(python3 -c 'import json,sys;print(max(s["t_end"] for s in json.load(open(sys.argv[1],encoding="utf-8"))["segments"]))' "${JSON}")"
# Garde-fou AVANT encodage : un storyboard trop long est refuse tout de suite.
python3 -c 'import sys; sys.exit(0 if float(sys.argv[1])<=float(sys.argv[2]) else 1)' "${DUR}" "${BUDGET}" \
  || { echo "ERREUR : storyboard ${DUR} s > budget ${BUDGET} s — corriger storyboard.json." >&2; exit 1; }

# Fichiers temporaires (legendes + sortie partielle) nettoyes quoi qu'il arrive : jamais de livrable tronque.
ASS="$(mktemp --suffix=.ass)"
OUT_TMP="$(mktemp -p "${ROOT}" --suffix=.part.mp4)"
trap 'rm -f "${ASS}" "${OUT_TMP}"' EXIT

# Piste de legendes ASS depuis le storyboard (source unique, texte echappe : cf. gen_ass.py).
python3 "${HERE}/gen_ass.py" "${JSON}" >"${ASS}"

echo "== Assemblage du Clip Chrono (budget <= ${BUDGET} s, duree conservee ${DUR} s) =="
# -ss/-t : recadrage au top AVANT et a la duree utile. Une seule entree video : zero coupe (pas de montage).
# file: : empeche ffmpeg d'interpreter un nom contenant ':' comme un protocole.
# ass : incruste les legendes. libx264/yuv420p/+faststart : lecture universelle (jury, navigateur).
ffmpeg -nostdin -y -ss "${START}" -i "file:${RAW}" -t "${DUR}" \
  -vf "ass=${ASS}" -an \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -movflags +faststart \
  "${OUT_TMP}"

# Garde-fous durs sur la sortie partielle : jamais > budget, et pas tronquee (prise trop courte / t_debut trop grand).
ACTUAL="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "${OUT_TMP}")"
echo "== Duree mesuree : ${ACTUAL} s =="
python3 -c 'import sys; d,lo,hi=map(float,sys.argv[1:4]); sys.exit(0 if lo-0.5<=d<=hi else 1)' "${ACTUAL}" "${DUR}" "${BUDGET}" \
  || { echo "ERREUR : clip ${ACTUAL} s hors bornes [${DUR}-0.5 ; ${BUDGET}] — prise trop courte ou > budget. Abandon." >&2; exit 1; }

# Succes seulement : on remplace l'ancien livrable maintenant (jamais avant d'etre sur du nouveau).
mv -f "${OUT_TMP}" "${OUT}"
echo "OK — ${OUT} ($(du -h "${OUT}" | cut -f1), ${ACTUAL} s, sans coupe)."
