#!/usr/bin/env bash
# Audit de configuration RESILIENCE-ALPHA.
# Vérifie les règles de durcissement les plus critiques sur le dépôt.
# Code retour 0 = conforme, 1 = au moins un problème (contrat réutilisable par la future CI).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

FAIL=0
pass() { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=1; }

echo "== Audit durcissement RESILIENCE-ALPHA =="

# 1. Socket Docker : le moteur de remédiation ne doit JAMAIS y toucher, et aucun
#    montage ne doit être en lecture-écriture. Les montages read-only du
#    docker-socket-proxy et de Promtail (découverte de logs) sont légitimes.
echo "[1] Socket Docker brut"
sock_problem=0
# 1a. Le code du MOTEUR ne référence jamais le socket. Le médiateur dédié
#     (remediation/proxy/), les tests, le Dockerfile et les commentaires/docstrings
#     de mise en garde sont exclus : seul l'usage réel dans le code applicatif compte.
engine_sock="$(grep -RIn 'docker\.sock' remediation/ 2>/dev/null \
  | grep -vE '/proxy/|/tests/|Dockerfile|\.md:' \
  | grep -vE '^[^:]+:[0-9]+:[[:space:]]*#' \
  | grep -viE 'jamais|ne monte|parle http|déclare pas|uniquement')"
if [[ -n "${engine_sock}" ]]; then
  fail "le code du moteur de remédiation référence /var/run/docker.sock (doit passer par le proxy)"
  echo "${engine_sock}"
  sock_problem=1
fi
# 1b. Aucun montage du socket en lecture-écriture (absence de suffixe :ro).
if grep -RIn --include='*.yml' --include='*.yaml' -- '- /var/run/docker.sock:/var/run/docker.sock' infra/ remediation/ 2>/dev/null \
     | grep -v ':ro' | grep -q .; then
  fail "montage de /var/run/docker.sock en lecture-écriture détecté (doit être :ro et médié)"
  grep -RIn --include='*.yml' --include='*.yaml' -- '- /var/run/docker.sock:/var/run/docker.sock' infra/ remediation/ 2>/dev/null | grep -v ':ro'
  sock_problem=1
fi
[[ "${sock_problem}" -eq 0 ]] && pass "socket Docker médié (proxy/promtail en lecture seule, remédiation n'y touche pas)"

# 2. Pas de conteneur privileged: true
echo "[2] Conteneurs privilégiés"
if grep -RIn --include='*.yml' --include='*.yaml' 'privileged:[[:space:]]*true' infra/ 2>/dev/null | grep -q .; then
  fail "privileged: true détecté"
  grep -RIn --include='*.yml' --include='*.yaml' 'privileged:[[:space:]]*true' infra/ 2>/dev/null
else
  pass "aucun conteneur privilégié"
fi

# 3. Secrets potentiels en clair (hors exemples/docs/tests explicitement factices).
echo "[3] Secrets en clair"
# Le filtre d'exclusion s'applique au CONTENU seul (on retire le préfixe `chemin:ligne:` via awk),
# sinon un fichier dont le CHEMIN contient « test »/« latest »/« contest » échapperait au scan.
# Les répertoires de tests sont exclus explicitement ; on couvre aussi .sh/.conf/.json.
secret_hits="$(grep -RInE '(password|secret|token|api[_-]?key)[[:space:]]*[:=][[:space:]]*["'\''][^"'\'' ]{8,}' \
     --include='*.py' --include='*.ts' --include='*.tsx' --include='*.yml' --include='*.yaml' \
     --include='*.sh' --include='*.conf' --include='*.json' \
     --exclude-dir='tests' --exclude-dir='node_modules' --exclude-dir='__pycache__' \
     services/ ml/ remediation/ dashboard/ assistant/ infra/ scripts/ security/ 2>/dev/null \
     | awk -F: '{ c=$0; sub(/^[^:]*:[^:]*:/,"",c); if (c !~ /(change-me|example|fake|dummy|test|os\.environ|getenv|process\.env|VITE_|env\()/) print }')"
if [[ -n "${secret_hits}" ]]; then
  fail "secret potentiel en clair détecté"
  printf '%s\n' "${secret_hits}"
else
  pass "aucun secret en clair évident"
fi

# 4. Fichiers de clés age jamais présents dans le dépôt.
echo "[4] Clés age"
if find . -name 'keys.txt' -o -name '*.age' 2>/dev/null | grep -v node_modules | grep -q .; then
  fail "fichier de clé age présent dans le dépôt"
else
  pass "aucune clé age dans le dépôt"
fi

# 5. Exposition réseau : WAF HTTP, et Mosquitto sur l'IP du PA si le profil iot est actif.
echo "[5] Exposition réseau (WAF HTTP + MQTT sur le PA)"
COMPOSE="infra/compose/docker-compose.yml"
if [[ -f "${COMPOSE}" ]]; then
  # Repère les services (indent 2) du bloc `services:` qui déclarent une clé `ports:` (indent 4).
  offenders="$(awk '
    /^[A-Za-z0-9_-]+:/        { in_services = ($0 ~ /^services:/) ; next }
    in_services && /^  [A-Za-z0-9_-]+:/ { svc = $1; sub(/:$/, "", svc) }
    in_services && /^    ports:/        { if (svc != "waf" && svc != "mosquitto") print svc }
  ' "${COMPOSE}" | sort -u)"
  if [[ -n "${offenders}" ]]; then
    fail "des services autres que WAF/Mosquitto publient des ports : ${offenders}"
  elif ! grep -Fq 'ports: ["${MQTT_BIND_ADDR:-192.168.137.1}:1883:1883"]' "${COMPOSE}"; then
    fail "Mosquitto doit être lié uniquement à 192.168.137.1:1883 (surchargeable par MQTT_BIND_ADDR)"
  elif [[ "${MQTT_BIND_ADDR:-192.168.137.1}" == "0.0.0.0" ]]; then
    fail "MQTT_BIND_ADDR=0.0.0.0 exposerait le broker sur toutes les interfaces"
  else
    pass "WAF HTTP et Mosquitto lié au PA ; DB/API/obs internes"
  fi
else
  fail "docker-compose.yml introuvable"
fi

# 6. Durcissement conteneurs : ancre no-new-privileges + cap_drop ALL présente.
echo "[6] Durcissement conteneurs (no-new-privileges, cap_drop ALL)"
if grep -q 'no-new-privileges:true' "${COMPOSE}" 2>/dev/null \
   && grep -qE '^\s*cap_drop:' "${COMPOSE}" 2>/dev/null \
   && grep -qE '^\s*-\s*ALL\s*$' "${COMPOSE}" 2>/dev/null; then
  pass "ancre de durcissement présente (no-new-privileges + cap_drop: ALL)"
else
  fail "durcissement manquant : no-new-privileges et/ou cap_drop: ALL absents du compose"
fi

# 7. Réseaux sans sortie : data (DB) ET obs (observabilité) en internal (P4S-02).
echo "[7] Réseaux internes (data + obs sans sortie Internet)"
net_internal() {  # 1=nom du réseau ; 0 si `internal: true` présent dans son bloc
  awk -v net="  $1:" '
    $0==net {d=1;next}
    d && /internal:[[:space:]]*true/ {found=1}
    /^  [A-Za-z0-9_-]+:/ && $0!=net {d=0}
    END{exit !found}' "${COMPOSE}" >/dev/null 2>&1
}
if net_internal data && net_internal obs; then
  pass "réseaux data et obs en internal: true (DB et observabilité non joignables depuis l'hôte)"
else
  net_internal data || fail "le réseau data n'est pas internal: true (DB potentiellement exposée)"
  net_internal obs  || fail "le réseau obs n'est pas internal: true (observabilité avec sortie Internet)"
fi

echo
if [[ "${FAIL}" -eq 0 ]]; then
  echo "== Audit OK =="
else
  echo "== Audit : problèmes détectés =="
fi
exit "${FAIL}"
