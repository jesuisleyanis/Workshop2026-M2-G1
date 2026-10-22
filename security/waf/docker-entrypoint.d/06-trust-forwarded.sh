#!/bin/sh
# Mode « IP réelle » (REAL_IP=1, voir infra/caddy/README.md) : un reverse proxy NATIF Windows (Caddy)
# voit la vraie IP du client (Docker Desktop la masque derrière sa passerelle) et la transmet dans
# X-Forwarded-For. Le WAF ne doit croire cet en-tête QUE s'il vient de ce proxy : WAF_TRUST_FORWARDED_FROM
# liste les sources de confiance (passerelles Docker, seules à porter le trafic publié — publié en
# 127.0.0.1 seulement dans ce mode, donc joignable par le seul Caddy).
# Vide (défaut) : aucune confiance -> un client ne peut jamais choisir son IP (blocage, rate-limit).
set -eu
OUT="/etc/nginx/conf/realip.conf"
{
  echo "# généré par 06-trust-forwarded.sh — ne pas éditer"
  if [ -n "${WAF_TRUST_FORWARDED_FROM:-}" ]; then
    for src in $(echo "${WAF_TRUST_FORWARDED_FROM}" | tr ',' ' '); do
      # IP ou plage CIDR littérale uniquement (la valeur finit dans la conf Nginx : aucune injection).
      if ! echo "${src}" | grep -Eq '^[0-9A-Fa-f:.]+(/[0-9]{1,3})?$'; then
        echo "06-trust-forwarded: source invalide refusée : ${src}" >&2
        exit 1
      fi
      echo "set_real_ip_from ${src};"
    done
    echo "real_ip_header X-Forwarded-For;"
    echo "real_ip_recursive off;"
  fi
} > "${OUT}"
if [ -n "${WAF_TRUST_FORWARDED_FROM:-}" ]; then
  echo "06-trust-forwarded: X-Forwarded-For accepté depuis ${WAF_TRUST_FORWARDED_FROM}"
fi
exit 0
