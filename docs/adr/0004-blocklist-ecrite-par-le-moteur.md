# ADR 0004 — Blocage d'IP : liste écrite par le moteur, rechargée par le WAF

- **Statut :** accepté
- **Contexte :** l'action `waf_block_ip` / `waf_blacklist_ip` devait, via un playbook Ansible lancé depuis le conteneur de remédiation, écrire la liste de blocage sur l'hôte puis exécuter `docker exec … nginx -s reload`. Cela ne pouvait pas fonctionner : le moteur est non-root, sans accès à l'hôte ni aux playbooks, et `docker-socket-proxy` (ADR 0002) n'autorise que quatre appels dont aucun ne recharge nginx. Élargir le proxy (`exec`, `kill`) aurait annulé l'intérêt de l'ADR 0002. Deuxième écueil : un bind mount de **fichier** garde l'ancien inode quand l'écrivain renomme le fichier.
- **Décision :**
  - le moteur écrit la liste lui-même (`remediation/actions/blocklist.py`) : IP validée, **renommage atomique** dans un **dossier** (`security/waf/blocklist/`), plafonné, idempotent. Seul droit ajouté : écrire dans ce dossier (et lire Loki, réseau `obs`) ;
  - le WAF monte ce dossier **en lecture seule** et **se recharge seul** (`security/waf/docker-entrypoint.d/98-blocklist-watch.sh` : empreinte des `*.conf`, `nginx -t` puis `nginx -s reload`) ; une liste invalide ne remplace jamais la conf en service ;
  - pour `web_attack`, l'IP à bloquer vient de **Loki** (`source: from_loki` : la source la plus fréquente des `waf_blocked` des 120 s, issue de `$remote_addr` donc non falsifiable) — le detector ne voit que des métriques agrégées et n'émet pas `source_ip` ;
  - `waf_deny_ip.yml` reste le geste de l'**opérateur** (PRA), hors du moteur ; `ALLOWED_PLAYBOOKS` ne contient plus que `pg_restore.yml`.
- **Alternatives écartées :**
  - autoriser `kill -HUP` / `exec` dans haproxy : élargit le proxy que l'ADR 0002 voulait minimal ;
  - redémarrer le conteneur WAF (verbe `restart` déjà autorisé) : coupe la seule porte d'entrée à chaque blocage ;
  - volume nommé partagé : plus propre sur Linux, mais la liste n'est plus inspectable/éditable dans le dépôt ni par `attacks/reset.sh`.
- **Conséquences :**
  - (+) Chaîne vérifiée de bout en bout (`tests/e2e`, `security/waf/tests/test_waf_image.py` sur la vraie image) ; aucun verbe Docker de plus.
  - (+) Un WAF compromis ne peut toujours pas débloquer une source (montage en lecture seule).
  - (−) Le moteur gagne un droit d'écriture sur un dossier de configuration du WAF : une compromission du moteur peut bloquer des IP (déni de service ciblé, plafonné) mais pas en débloquer au-delà de ce qu'il a écrit lui-même ; il ne peut pas modifier la conf nginx.
  - (−) Sur hôte Linux, le dossier doit être inscriptible à l'uid 10001 : `make prepare-blocklist` le passe en `0777` — acceptable sur le poste de démo mono-utilisateur, **pas sur un hôte partagé** (tout utilisateur local pourrait alors débloquer une source) ; hors démo, `chown 10001` + `0750`.
  - (−) Une compromission du moteur permet d'écrire du texte arbitraire dans les `*.conf` du dossier : la syntaxe `geo` ne permet pas d'injecter un `server`/`location`, et `nginx -t` précède tout rechargement (une liste invalide est ignorée), mais le moteur peut bloquer des sources à tort jusqu'au plafond.
  - (−) Le moteur est sur le réseau `obs` (lecture de Loki) : segmentation à reprendre (ROADMAP I14).
