# Mode « IP réelle » — proxy natif Windows (Caddy)

## Pourquoi

Sous Docker Desktop (Windows / WSL2), tout le trafic publié entre dans la stack par une **passerelle Docker** :
le WAF voit le même client (`172.31.0.1`) pour le PC attaquant, le jury et les utilisateurs. Conséquences :
blocage d'IP impossible (il couperait tout le monde — la passerelle est donc protégée), limitation de débit de
fait globale, rate-limit de login partagé.

Caddy tourne **directement sous Windows** : il voit la vraie IP du client et la transmet au WAF.

```
PC attaquant ──► Caddy (Windows, :443) ──X-Forwarded-For: <vraie IP>──► WAF (127.0.0.1:8443) ──► API
```

## Ce que ça débloque

| Avant (mode par défaut) | Avec REAL_IP=1 + Caddy |
|---|---|
| `waf_block_ip` / `waf_blacklist_ip` refusés (passerelle protégée) | l'IP de l'attaquant est désignée (Loki) et **bloquée** |
| limitation de débit WAF globale | **par client** : l'attaquant est écrêté, pas les autres |
| rate-limit de login partagé par tous | par client |

## Sécurité : pourquoi X-Forwarded-For est digne de confiance

1. Le WAF n'est publié **que sur 127.0.0.1** (`docker-compose.realip.yml`) : depuis le hotspot, seul Caddy est
   joignable ; personne ne peut contourner Caddy.
2. Caddy **écrase** `X-Forwarded-For` avec l'IP qu'il voit (`header_up X-Forwarded-For {remote_host}`).
3. Le WAF ne croit cet en-tête que venant des passerelles Docker (`WAF_TRUST_FORWARDED_FROM`), c.-à-d. du trafic
   publié en local. En mode par défaut, la liste est **vide** : aucun client ne peut choisir son IP.
4. Les protections restent : réseaux Docker internes jamais bloqués (`NEVER_BLOCK_IPS`), IP validées.

## Mise en place (PC hôte)

1. Installer Caddy (PowerShell) : `winget install --id CaddyServer.Caddy -e`, puis rouvrir Git Bash.
2. Pare-feu Windows : autoriser **Caddy** en entrée sur le réseau du hotspot (ports 80/443) — à la première
   exécution, Windows le propose.
3. Lever la stack en mode IP réelle : `make down` puis `REAL_IP=1 make up-full` (puis `REAL_IP=1 make ui`).
4. Lancer Caddy (fenêtre dédiée, laisser tourner) : `make caddy`.
5. Vérifier : `make verify` (passe par Caddy) ; depuis le PC attaquant, `https://192.168.137.1` répond ; les logs du
   WAF montrent l'IP `192.168.137.x` du PC attaquant :
   `docker logs resilience-g1-waf-1 --since 1m | grep client_ip`.

Retour au mode par défaut : arrêter Caddy, `make down`, `make up-full`.

> Toutes les commandes `make` d'une session doivent porter le même `REAL_IP` (sinon Compose recrée le WAF avec
> l'autre publication de ports). Astuce : `export REAL_IP=1` dans le terminal.
