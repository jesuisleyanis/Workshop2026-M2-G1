# Cahier des charges - `dashboard` (supervision)

> Exigences tracées : **R4** (interface de supervision : composants, événements, alertes, avancement de la reprise) et **R20** (démo visible **avant / pendant / après** l'incident). Contrats : [`docs/contracts.md`](../docs/contracts.md). Cadrage global : [`CAHIER-DES-CHARGES.md`](../CAHIER-DES-CHARGES.md).

## 1. Rôle

Écran de **supervision pour le jury / l'opérateur**, projeté et filmé pour le Clip Chrono (≤ 60 s, sans coupe). Il montre en direct la boucle *Zero-Touch Recovery* : la santé des services, le score d'anomalie du ML, la timeline **détection -> décision -> action -> vérification**, le MTTD / MTTR, la dernière transaction de vérification, et donne accès à Grafana. La boucle automatique reste **sans intervention humaine** : l'écran ne pilote jamais la remédiation d'un incident. Seule exception, hors boucle : le panneau « Commande opérateur » (D18) permet une action manuelle **explicitement confirmée** (liste blanche du moteur).

Design « ZTR Supervision » (console sombre, accent violet, polices Geist auto-hébergées) : barre latérale (état du flux, horloge, source, répétition, Grafana), bandeau de phase, rangée d'indicateurs, courbe du score sur 2 min, timeline en 4 cartes, actions, santé, signaux, playbooks, preuves. Les états sont portés par du **texte** (pas seulement par la couleur).

## 2. Exigences

| # | Exigence | Réalisation |
|---|---|---|
| D1 (R20) | Mise en avant de la phase **AVANT / PENDANT / APRÈS** | `PhaseBanner` + `lib/state.ts#derivePhase` |
| D2 (R4) | État des services (santé) | `ServicesGrid` (message `health`) |
| D3 (R4) | Score d'anomalie en direct, seuil, historique **par service** (fenêtre 2 min, onglets, marqueurs détection / vérifié) | `ScoreCard` + `ScoreChart` (messages `score` et `anomaly_detected`) |
| D4 (R4) | Timeline d'incident détection -> décision -> action -> vérification | `IncidentTimeline` + `buildTimeline` |
| D5 (R4) | MTTD / MTTR (MTTR live pendant l'incident) | `MetricsCards` |
| D6 | Dernière transaction de vérification (`verify_tx`) : statut, durée, ancienneté | `VerificationCard` |
| D7 | Liens vers Grafana ; preuves de l'anomalie ouvertes dans Explore (Prometheus / Loki pré-remplis) | `GrafanaLinks`, `EvidencePanel` |
| D8 | Temps réel par SSE, reconnexion automatique, état de connexion visible | `useRemediationStream`, `Sidebar` |
| D9 | Messages non conformes comptés et signalés (pas de perte silencieuse) | `rejected` dans l'état, en-tête |
| D10 | « Réinitialiser la vue » (reprise de clip) : écarte l'incident affiché, revient à AVANT, conserve courbes et santé ; les événements tardifs de l'incident écarté sont ignorés | `reducer` action `reset` (`dismissed`) |
| D11 | Image durcie : non-root, healthcheck, statique + proxy SSE | `Dockerfile`, `docker/` |
| D12 | Actions de remédiation : plan annoncé par le moteur + résultat de chaque action | `ActionsPanel` (`remediation_started` / `remediation_action`) |
| D13 | Signaux dominants (z-score des `features_top`) et playbooks de la table de décision, règle active surlignée | `SignalsPanel`, `PlaybooksPanel` (miroir d'affichage de `remediation/decision_table.yml`) |
| D14 | Simulation locale (répétition sans stack) : mêmes trames JSON que le moteur, validées par le même parseur, **toujours signalée** à l'écran | `lib/simulator.ts`, `VITE_STREAM_SOURCE` |
| D15 | Déclencheurs de répétition : en simulation, ou en flux réel **en dev uniquement** (mock `GET /trigger`) ; masqués en prod | `Sidebar`, `LIVE_TRIGGERS` |
| D16 | Onglet « Assistant » : UI de l'assistant RAG en iframe same-origin (`/assistant/`), supervision gardée montée | `AssistantTab` (`VITE_ASSISTANT_URL`), onglets dans `App` |
| D17 | « Rapport d'incident » : résumé DSI **à la demande** (`POST /assistant/api/v1/summarize`, mis en cache par incident, badge « mode dégradé ») ; post-mortem téléchargé en `postmortem-<id>.md` (`/postmortem`), actif seulement pour un incident terminé (vérifié ou en échec) | `IncidentReportPanel` (`components/OperatorTools.tsx`) |
| D18 | « Commande opérateur » : texte libre -> proposition de l'assistant (`POST /assistant/api/v1/propose`) -> motif optionnel -> **Confirmer** / Annuler. Rien n'est exécuté sans clic sur Confirmer (désactivé pendant la requête) ; Confirmer appelle `POST /remediation/manual-actions` et affiche `status` / `detail` ; les 422 (`action_refused`, `invalid_params`…) sont affichés en clair ; `proposal: null` affiche `message` sans bouton Confirmer | `OperatorCommandPanel` (`components/OperatorTools.tsx`) |

### Source des événements et déclencheurs

- `VITE_STREAM_SOURCE=live` (défaut, démo jury) : flux réel uniquement. Une coupure affiche « Flux interrompu », **jamais** de bascule silencieuse vers des données générées.
- `auto` : flux réel ; s'il n'a **jamais** pu s'ouvrir, bascule une fois en simulation avec le bandeau « Flux injoignable — simulation locale active ». Un flux ouvert puis coupé reste en reconnexion.
- `simulation` : simulation d'emblée. Bouton « Passer en simulation » / « Réessayer le flux réel » dans tous les modes.
- Les déclencheurs injectent un **incident de démonstration** (simulation locale ou mock) ; ils ne pilotent jamais le moteur de remédiation réel (nginx n'en proxifie que `GET /stream` et `POST /manual-actions`, cette dernière réservée à D18). En démo, les attaques partent du PC Attaquant.

### Définition des phases (R20)

| Phase | Condition |
|---|---|
| **AVANT** | aucun incident observé : système nominal |
| **PENDANT** | dernier incident ouvert : détecté, en remédiation, ou en échec / escalade (`remediation_failed`) |
| **APRÈS** | dernier incident clos par une vérification `verify_tx` **OK** (`remediation_verified`) |

Une vérification en échec ne fait **jamais** passer en APRÈS. Un nouvel incident après un APRÈS repasse en PENDANT.

## 3. Interfaces consommées

Principale : le **flux SSE du moteur de remédiation**, `GET http://remediation:8005/stream` (docs/contracts.md : « SSE/WebSocket -> Dashboard »). Le navigateur n'appelle jamais `remediation:8005` directement : il ouvre `<VITE_REMEDIATION_BASE>/stream` (défaut `/remediation/stream`), proxifié par Vite en dev et par nginx en prod.

À la demande de l'opérateur (D17, D18), via les mêmes proxys :

| Appel navigateur | Cible | Corps -> réponse |
|---|---|---|
| `POST /assistant/api/v1/summarize` | assistant | `{incident}` (objet `Incident` de l'état) -> `{summary, degraded, model}` |
| `POST /assistant/api/v1/postmortem` | assistant | `{incident}` -> `{markdown, degraded, model}` |
| `POST /assistant/api/v1/propose` | assistant | `{command}` (3..300 car.) -> `{proposal: {action, params, explanation} \| null, message, degraded}` |
| `POST /remediation/manual-actions` | moteur (`/manual-actions`, Bearer injecté par nginx) | `{action, params, reason?}` -> `{incident_id, action, status, detail}` ; 422 `invalid_request` / `invalid_params` / `action_refused` |

Erreurs au format `{error:{code,message,request_id}}`, affichées « `code : message` » ; service injoignable (ex. simulation sans stack) -> « Service injoignable », sans effet sur le flux.

### Schémas

- **AnomalyEvent** : schéma figé du contrat §3 (`schema_version`, `event_id`, `ts`, `source`, `service`, `anomaly_score`, `threshold`, `incident_type`, `features_top[{name,value,z}]`, `evidence{prometheus_query,loki_query}`). Validé strictement par `parseAnomalyEvent` : `schema_version` majeure 1, `incident_type` dans l'énumération figée (`service_flood`, `auth_abuse`, `web_attack`, `data_corruption`, `unknown`). Un événement non conforme est rejeté et compté.
- **Événements normalisés** de §1 repris comme noms d'événements SSE : `anomaly_detected`, `remediation_started`, `remediation_action`, `remediation_verified`, `remediation_failed`.

### Hypothèses d'enveloppe SSE (à aligner avec `remediation/`)

Le contrat fige l'AnomalyEvent et les noms d'événements, **pas** la forme des messages du flux. Le dashboard suppose des trames SSE avec `event: <nom>` et `data: <JSON>` (si `event:` est absent, le type est lu dans `type` ou `event` du JSON) :

| `event:` | `data` (JSON) | Effet |
|---|---|---|
| `health` | `{ts?, services:[{name, status:"up"\|"degraded"\|"down", detail?}]}` | `ServicesGrid` (fusion par nom) |
| `score` | `{ts?, service?, anomaly_score, threshold?}` (période ~1 s, gauge `resilience_anomaly_score`) | jauge + historique |
| `anomaly_detected` | **AnomalyEvent** + `incident_id` (repli : `event_id`) | ouvre l'incident, étape Détection |
| `remediation_started` | `{ts, incident_id, incident_type?, service?, actions:[{type,params?}], dry_run?}` | étape Décision |
| `remediation_action` | `{ts, incident_id, action:"<type>", result:"ok"\|"failed"\|"skipped", detail?, attempt?}` | étape Action |
| `remediation_verified` | `{ts, incident_id, mttd_seconds?, mttr_seconds?, verify_tx:{ok, tx_id?, ts?, duration_ms?}}` | étape Vérification, MTTD/MTTR, passe en APRÈS |
| `remediation_failed` | `{ts, incident_id, reason}` | échec / escalade, reste PENDANT |
| `verify_tx` | `{ts?, ok, tx_id?, duration_ms?}` (transactions de contrôle périodiques, dont l'état AVANT) | carte « dernière vérification » |

Points de vigilance côté moteur :
- Pour que **MTTD** s'affiche, `mttd_seconds` doit être fourni (le dashboard ne connaît pas l'instant de début de l'attaque). **MTTR** : `mttr_seconds` si fourni, sinon repli détection -> `verify_tx` OK.
- Les noms d'actions suivent le catalogue §4 (`waf_block_ip`, `restart_service`, ...). Un nom inconnu est affiché tel quel.
- Un seul point d'adaptation en cas d'écart : `src/lib/parse.ts` (couvert par `src/lib/parse.test.ts`).
- `npm run mock` fournit un faux moteur conforme à ce tableau pour le dev et les répétitions.

## 4. Variables d'environnement

| Variable | Quand | Défaut | Rôle |
|---|---|---|---|
| `VITE_REMEDIATION_BASE` | build | `/remediation` | Base du flux SSE (`<base>/stream`) |
| `VITE_GRAFANA_BASE` | build | `http://localhost:3000` | Base des liens Grafana (ouverts dans un nouvel onglet : doit être joignable **depuis le navigateur du jury**) |
| `VITE_STREAM_SOURCE` | build | `live` | `live` \| `auto` \| `simulation` (voir §2) |
| `VITE_LIVE_TRIGGERS` | build | _vide_ | `true` : déclencheurs aussi en flux réel hors dev (pour un mock servi en preview uniquement) |
| `VITE_ASSISTANT_URL` | build | `/assistant/` | URL de l'UI de l'assistant (iframe ; slash final requis) |
| `REMEDIATION_PROXY_TARGET` | dev | `http://localhost:8005` | Cible du proxy Vite pour `/remediation` |
| `ASSISTANT_PROXY_TARGET` | dev | `http://localhost:8006` | Cible du proxy Vite pour `/assistant` |
| `REMEDIATION_UPSTREAM` | runtime (conteneur) | `remediation:8005` | Hôte:port du moteur pour le proxy nginx |
| `ASSISTANT_UPSTREAM` | runtime (conteneur) | `assistant:8006` | Hôte:port de l'assistant RAG pour le proxy nginx |
| `REMEDIATION_AUTH_HEADER` | runtime | _vide_ | Valeur complète du header `Authorization` injecté par nginx (ex. `Bearer <token SOPS>`). Vide = aucun header |
| `DNS_RESOLVER` | runtime | `127.0.0.11` | Résolveur DNS Docker (résolution paresseuse de `remediation`) |

## 5. Exécution et exposition

- Dev : `npm run dev` sur le port **5174** (strict).
- Prod : conteneur nginx non-root écoutant **8080**, réseau `app` (doit joindre `remediation:8005`). nginx sert le statique **et** proxifie **uniquement** `GET /remediation/stream` (SSE : `proxy_buffering off`, timeout 1 h), `POST /remediation/manual-actions` (corps ≤ 4 Ko, jeton injecté) et les routes de l'assistant RAG `GET /assistant/`, `GET /assistant/static/*`, `POST /assistant/api/v1/(ask|summarize|postmortem|propose)` (préfixe retiré, timeout 130 s) ; tout autre `/remediation/*` ou `/assistant/*` renvoie 404, et toute autre méthode 403. L'API `/events` du moteur n'est jamais atteignable depuis le navigateur. Healthcheck : `GET /healthz`.
- Le build utilise `base: './'` : l'app peut être servie à la racine d'un hôte ou sous un sous-chemin (dans ce cas régler `VITE_REMEDIATION_BASE` au build en conséquence).

## 6. Sécurité

- Le moteur de remédiation reste **hors réseau `edge`** ; le dashboard n'y accède que par le proxy nginx (flux en lecture seule + la seule route d'action manuelle). Le jeton éventuel est injecté côté serveur (variable d'environnement du conteneur, fournie via SOPS), **jamais dans le bundle**.
- **Le dashboard ne doit pas être publié publiquement sans contrôle d'accès** : toute personne qui l'atteint peut lire le flux de supervision. Options : publier sur l'hôte en `127.0.0.1` / réseau d'admin, ou le router via le WAF avec authentification.
- Image multi-stage, utilisateur `nginx`, CSP stricte (`default-src 'self'`, `connect-src 'self'`), `X-Frame-Options: DENY`, `nosniff` (sauf sur `/assistant/` : pas de `X-Frame-Options`, l'assistant pose sa propre CSP `frame-ancestors 'self'` pour être embarqué ; l'iframe same-origin est permise par `default-src 'self'`), `server_tokens off`, conf générée dans `/tmp` (compatible `read_only: true` + `tmpfs: /tmp`, `cap_drop: [ALL]`, `no-new-privileges`).
- Liens Grafana : `rel="noopener noreferrer"`. Polices Geist servies depuis le bundle (`@fontsource-variable/*`) : la CSP n'autorise aucun CDN.
- **Route d'action `POST /remediation/manual-actions`** : nginx y injecte le jeton du moteur, donc **quiconque atteint le dashboard peut l'appeler**. Sa protection repose uniquement sur (1) l'exposition réseau du dashboard (127.0.0.1 / réseau d'admin / WAF authentifié), (2) la confirmation explicite dans l'UI (non opposable à un appel direct), (3) la liste blanche du moteur (`waf_block_ip` hors IP protégées, `restart_service` limité à `RESTARTABLE_SERVICES`, 422 sinon) et sa journalisation. L'assistant ne fait que proposer : il n'appelle jamais le moteur.
- Pas de `dangerouslySetInnerHTML` : textes de l'assistant rendus en texte brut ; le post-mortem n'est pas rendu, seulement téléchargé.
- Pas de bouton d'attaque en prod : les déclencheurs de répétition n'existent qu'en simulation ou en dev (D15).

## 7. Tests (Vitest + Testing Library)

Parsing d'un AnomalyEvent conforme au contrat (exemple verbatim §3, énumération `incident_type`, cas invalides), parsing des messages du flux, reducer et timeline (4 étapes, échecs), reset (incident écarté ignoré), MTTD/MTTR, **garde AVANT / PENDANT / APRÈS** (logique et rendu `aria-current`), composants clés (courbe : géométrie de la fenêtre, onglets, marqueurs ; actions ; preuves ; playbooks), hook SSE (EventSource simulé : états, rejets, fermeture), rejeu de bout en bout d'un incident `service_flood`, **simulation locale** jusqu'à APRÈS (`data_corruption` => `restore_pg_dump` seul, jamais de redémarrage), bascule `auto`, déclencheur dev ; outils opérateur (`fetch` simulé) : résumé + mode dégradé, téléchargement du post-mortem, propose -> Confirmer -> `/remediation/manual-actions`, Annuler sans appel, `proposal: null` sans Confirmer, 422 du moteur affiché, service injoignable. Lancement : `npm run test` (Node ≥ 22.22 / 24.15, exigé par jsdom).
