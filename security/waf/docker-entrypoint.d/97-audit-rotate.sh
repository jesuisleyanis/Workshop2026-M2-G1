#!/bin/sh
# Borne le journal d'audit ModSecurity (tmpfs de 64 Mo) : ModSecurity v3 ne le fait pas, et un
# tmpfs plein fait perdre silencieusement les blocages suivants (waf-exporter ne les compte plus).
#
# Lancé de deux façons :
#   - par l'entrypoint de l'image (docker-entrypoint.d, sans argument) : se relance en tâche de
#     fond (`--loop`) puis rend la main à nginx ;
#   - `--once` : un seul contrôle (tests).
#
# Troncature en place (`: >`) et non rename/rotation : ModSecurity garde le fichier ouvert en
# ajout (O_APPEND), il continue d'écrire dans le même inode, et waf-exporter détecte la
# troncature (taille < position, ou début du fichier changé). Seuil bien en dessous du tmpfs :
# marge pour l'écriture entre deux contrôles. Fenêtre de perte : les lignes écrites depuis la
# dernière lecture de l'exporter (< 0,5 s) au moment de la troncature ; le compteur Prometheus
# reste valable pour tout ce qui a été lu avant.
LOG="${MODSEC_AUDIT_LOG:-/var/log/modsec/audit.json}"
MAX_BYTES="${AUDIT_LOG_MAX_BYTES:-16777216}"
INTERVAL_S="${AUDIT_ROTATE_INTERVAL_S:-5}"

rotate_once() {
    [ -f "$LOG" ] || return 0
    size=$(stat -c %s "$LOG" 2>/dev/null || echo 0)
    if [ "$size" -ge "$MAX_BYTES" ]; then
        : > "$LOG"
    fi
}

case "${1:-}" in
    --once) rotate_once ;;
    --loop) while :; do rotate_once; sleep "$INTERVAL_S"; done ;;
    *) "$0" --loop >/dev/null 2>&1 & ;;
esac
