# ADR 0002 — Remédiation via docker-socket-proxy (jamais le socket brut)

- **Statut :** accepté (J1)
- **Contexte :** le moteur de remédiation doit redémarrer/recréer des conteneurs. La voie « facile » consiste à monter `/var/run/docker.sock` dans le conteneur — ce qui équivaut à un accès root sur l'hôte. Le sujet (§3.4) et l'Axe 2 du jury sondent explicitement ce point.
- **Décision :** le moteur n'accède à Docker qu'à travers un `docker-socket-proxy` dont la config stricte est `remediation/proxy/haproxy.cfg` (haproxy). Elle n'autorise que **5 couples (méthode, chemin)** : `GET /_ping`, `GET /containers/json`, `GET /containers/{id}/json`, `POST /containers/{id}/restart`, et `POST /containers/{id}/kill` **uniquement avec `?signal=HUP`** (rechargement à chaud du WAF après mise à jour de la deny-list ; ajouté le 19/10/2026 avec le modèle d'exécution in-container, voir `infra/ansible/README.md`) — tout le reste renvoie 403. C'est plus restrictif que `tecnativa/docker-socket-proxy` (où `CONTAINERS=1`+`POST=1` autoriserait `POST /containers/create`, donc un conteneur privilégié). Défense en profondeur : le client `remediation/actions/docker_proxy.py` applique en plus la même liste blanche. Le socket n'est monté qu'au niveau du proxy, en lecture seule. L'API `/events` du moteur est authentifiée par un **Bearer statique interne** (`REMEDIATION_TOKEN` via SOPS) et le service reste sur le réseau `app`, jamais `edge`.
- **Alternative écartée :** `tecnativa/docker-socket-proxy` — plus simple à configurer mais granularité par *sections* d'API, moins fine que la liste blanche par chemin.
- **Conséquences :**
  - (+) Surface d'attaque fortement réduite ; réponse défendable devant le jury.
  - (+) `security/hardening/audit.sh` vérifie automatiquement l'absence de montage direct du socket.
  - (−) Une dépendance de plus et une configuration à maintenir ; coût négligeable.
