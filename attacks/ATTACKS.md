# Catalogue des attaques — ce que chaque test fait et ce qu'il éprouve

> Toutes ces attaques ciblent **uniquement le WAF du projet** (`192.168.137.1`), sur des
> **données fictives**, **bornées** en intensité/durée, **réversibles**, avec **kill-switch**
> (`run.sh --stop`). But : éprouver la chaîne détection → remédiation → `verify_tx`, pas
> causer des dégâts irréversibles. Lancement : `attacks/run.sh <nom>` ou la Console Red Team.

## Comment lire ce tableau

Chaque attaque vise une **facette de défense** précise. Le « succès » Red Team = mettre en
défaut cette facette ; le « succès » Blue = la chaîne détecte, remédie, et `verify_tx` repasse
OK **sans intervention humaine**.

---

## Scénarios-contrat (reliés à la table de remédiation)

Ces 4 scénarios déclarent leur contrat dans `scenarios/*.yml` (signal → incident_type →
remédiation attendue).

### `service_flood` — saturation
- **Ce que ça fait** : pic de requêtes borné sur `payment-api` (`POST /transactions`).
- **Facette éprouvée** : disponibilité sous charge.
- **Signal** : `rate(http_requests)` ↑, ratio 5xx ↑, latence p95 ↑.
- **Réponse Blue attendue** : `waf_block_ip` + `restart_service` → `verify_tx` OK.

### `auth_abuse` — abus d'authentification
- **Ce que ça fait** : rafale de connexions invalides (`POST /login`, mauvais mot de passe).
- **Facette éprouvée** : résistance au bruteforce / rate-limit.
- **Signal** : échecs 401 ↑, `auth_rate_limited` ↑.
- **Réponse Blue attendue** : `waf_block_ip` + `tighten_rate_limit`.

### `web_attack` — motifs offensifs applicatifs
- **Ce que ça fait** : requêtes au motif typé (injection SQL, traversée de chemin) pour
  déclencher les règles OWASP CRS du WAF — **pas** d'exploitation réelle.
- **Facette éprouvée** : filtrage applicatif (WAF/ModSecurity).
- **Signal** : `waf_blocked_total` ↑.
- **Réponse Blue attendue** : `confirm_waf_block` + `waf_blacklist_ip`.

### `data_corruption` — corruption de données (opérateur-only)
- **Ce que ça fait** : altération **réversible** de données fictives (renommage de table)
  côté PC Hôte — la base n'est pas exposée au PC Attaquant.
- **Facette éprouvée** : intégrité des données / correction (≠ disponibilité).
- **Signal** : `db_errors_total` ↑, `verify_tx` KO.
- **Réponse Blue attendue** : `restore_pg_dump` (restauration, pas un simple redémarrage).

---

## Campagne corrélée

### `campaign.sh` — Opération Triade
- **Ce que ça fait** : enchaîne 3 vagues décalées : `auth_abuse` (feinte) → `web_attack`
  (sonde) → `service_flood` (assaut).
- **Facette éprouvée** : **corrélation SOC** et remédiation d'**incidents successifs**.
- **Pourquoi c'est dur** : la défense doit traiter trois incidents distincts d'affilée et
  garder `verify_tx` OK tout du long.

---

## Techniques avancées (sans contrat figé — éprouvent les angles morts)

Lançables via `run.sh <nom>` ou le panneau « Techniques avancées » de la console.

### `rotation` — rotation de source
- **Ce que ça fait** : un `service_flood` dont **la source change à chaque requête**
  (en-têtes `X-Forwarded-For` et `User-Agent` variés).
- **Facette éprouvée** : **robustesse de la remédiation**. La remédiation bloque l'IP
  source (`waf_block_ip`) ; si la source tourne, le blocage d'une IP ne suffit plus.
- **Ce que ça révèle** : leur remédiation bloque-t-elle vraiment l'attaque, ou seulement
  une IP ? (indice : il faut bloquer un motif/compte, pas une seule IP).

### `pulse` — rafales pulsées
- **Ce que ça fait** : rafales **ON/OFF** (ex. 3 s d'attaque, 4 s de silence) au lieu d'un
  flot continu, dans les plafonds.
- **Facette éprouvée** : **seuils temporels**. Une règle SOC en `rate(...[1m])` lisse les
  pics intermittents et peut ne jamais franchir le seuil.
- **Ce que ça révèle** : le **détecteur ML** fait-il mieux que le seuil statique (son rôle,
  contrat §3) ? Sinon, l'attaque passe sous le radar.

### `recon` — reconnaissance
- **Ce que ça fait** : balayage léger d'endpoints sensibles (`/.env`, `/.git/config`,
  `/admin`, `/backup.zip`…) générant des 404.
- **Facette éprouvée** : **largeur de détection**. La reconnaissance ne fait pas de
  « gros » signal ; relève-t-elle une alerte (incident_type `unknown`) ?
- **Ce que ça révèle** : un angle mort SOC — voient-ils l'attaquant qui cartographie avant
  de frapper ?

### `replay` — rejeu de transaction
- **Ce que ça fait** : rejoue **la même** transaction (même `request_id` / `Idempotency-Key`).
- **Facette éprouvée** : **intégrité applicative / idempotence**. Pas de corruption : on
  vérifie si les doublons sont **rejetés**.
- **Ce que ça révèle** : l'API dédoublonne-t-elle, ou un rejeu crée-t-il des transactions
  en double ? (observable dans les logs `transaction_created`).

### `slow` — connexions lentes (approximation Slowloris, bornée)
- **Ce que ça fait** : ouvre un nombre **plafonné** de connexions maintenues **lentes**
  (transfert bridé) pendant la fenêtre, pour occuper le pool de connexions.
- **Facette éprouvée** : **résistance aux attaques de lenteur** (timeouts, limites de
  connexions) — une facette de disponibilité que `service_flood` (volume) ne couvre pas.
- **Ce que ça révèle** : des timeouts trop longs ou un pool non borné rendent le service
  indisponible sans pic de trafic visible.

---

## Garde-fous (rappel, pour toutes)

- Cible = le WAF du projet, **jamais** un tiers (hors périmètre = arrêt + coach).
- `run.sh` plafonne `rate ≤ 100/s` et `duration ≤ 60 s` ; `slow` plafonne les connexions.
- Kill-switch `run.sh --stop` ; retour à l'état « avant » `reset.sh`.
- Journal horodaté dans `attacks/.runlog` pour corréler avec MTTD/MTTR.
