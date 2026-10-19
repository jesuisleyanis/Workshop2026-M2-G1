#!/bin/sh
# Recharge nginx quand la liste de blocage change : le moteur de remédiation écrit
# blocked_ips.conf (dossier monté en lecture seule ici) mais n'a aucun moyen de joindre le WAF —
# ni `docker exec` (refusé par docker-socket-proxy), ni signal. C'est donc le WAF qui surveille.
#
# Lancé de deux façons :
#   - par l'entrypoint de l'image (docker-entrypoint.d, sans argument) : se relance en tâche de
#     fond (`--loop`) puis rend la main à nginx ;
#   - `--once` : un contrôle (tests) ; code 0 = rien à faire ou rechargé, 1 = liste invalide.
#
# Une liste invalide (ligne mal formée) ne casse jamais le WAF : `nginx -t` est lancé AVANT le
# reload, la conf en service reste inchangée, et l'erreur part sur stderr. La même empreinte n'est
# jamais retestée tant que le fichier ne change pas (pas de spam toutes les secondes).
DIR="${BLOCKLIST_DIR:-/etc/nginx/blocklist}"
INTERVAL_S="${BLOCKLIST_WATCH_INTERVAL_S:-1}"
STATE="${BLOCKLIST_WATCH_STATE:-/tmp/blocklist.cksum}"

fingerprint() {
    # taille + contenu de tous les *.conf du dossier (celui du `include` nginx) : un renommage
    # atomique change l'inode mais pas forcément l'horodatage ; aucun fichier = empreinte stable
    cat "$DIR"/*.conf 2>/dev/null | cksum
}

check_once() {
    current=$(fingerprint)
    previous=$(cat "$STATE" 2>/dev/null || echo "")
    [ "$current" = "$previous" ] && return 0
    if nginx -t >/dev/null 2>&1; then
        nginx -s reload >/dev/null 2>&1 || { echo "blocklist-watch: reload refusé" >&2; return 1; }
        echo "$current" > "$STATE"
        return 0
    fi
    echo "$current" > "$STATE"      # ne pas retester la même liste invalide à chaque tour
    echo "blocklist-watch: liste de blocage invalide, rechargement annulé (nginx -t)" >&2
    return 1
}

case "${1:-}" in
    --once) check_once ;;
    --loop)
        # empreinte initiale = celle que nginx lit au démarrage : pas de reload inutile
        fingerprint > "$STATE"
        while :; do check_once; sleep "$INTERVAL_S"; done ;;
    *) "$0" --loop >/dev/null & ;;      # stderr conservé : l'erreur « liste invalide » doit se voir
esac
