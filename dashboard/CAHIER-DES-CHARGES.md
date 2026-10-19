# Cahier des charges - `dashboard` (supervision)

> Exigences tracées : **R4** (interface de supervision : composants, événements, alertes, avancement de la reprise) et **R20** (démo visible **avant / pendant / après** l'incident). Contrats : [`docs/contracts.md`](../docs/contracts.md). Cadrage global : [`CAHIER-DES-CHARGES.md`](../CAHIER-DES-CHARGES.md).

## 1. Rôle

Écran de **supervision pour le jury / l'opérateur**, projeté et filmé pour le Clip Chrono (≤ 60 s, sans coupe). Il montre en direct la boucle *Zero-Touch Recovery* : la santé des services, le score d'anomalie du ML, la timeline **détection -> décision -> action -> vérification**, le MTTD / MTTR, la dernière transaction de vérification, et donne accès à Grafana. Il est **en lecture seule** : aucune action de remédiation n'est déclenchée depuis l'écran (pas d'intervention humaine dans la boucle).

Conception pour la lisibilité à distance : thème sombre à fort contraste, très gros caractères, états portés par du **texte** (pas seulement par la couleur), animations discrètes (désactivées si `prefers-reduced-motion`).

## 2. Exigences

| # | Exigence | Réalisation |
|---|---|---|
| D1 (R20) | Mise en avant de la phase **AVANT / PENDANT / APRÈS** | `PhaseBanner` + `lib/state.ts#derivePhase` |
| D2 (R4) | État des services (santé) | `ServicesGrid` (message `health`) |
| D3 (R4) | Score d'anomalie en direct, seuil, historique | `ScoreGauge` (message `score` et `anomaly_detected`) |
| D4 (R4) | Timeline d'incident détection -> décision -> action -> vérification | `IncidentTimeline` + `buildTimeline` |
| D5 (R4) | MTTD / MTTR (MTTR live pendant l'incident) | `MetricsCards` |
| D6 | Dernière transaction de vérification (`verify_tx`) | `VerificationCard` |
| D7 | Liens vers Grafana | `GrafanaLinks` (`VITE_GRAFANA_BASE`) |
| D8 | Temps réel par SSE, reconnexion automatique, état de connexion visible | `useRemediationStream` |
| D9 | Messages non conformes comptés et signalés (pas de perte silencieuse) | `rejected` dans l'état, `Header` |
| D10 | Bouton « Réinitialiser la vue » (reprise de clip) : remet l'affichage à AVANT | `reducer` action `reset` |
| D11 | Image durcie : non-root, healthcheck, statique + proxy SSE | `Dockerfile`, `docker/` |

### Définition des phases (R20)

| Phase | Condition |
|---|---|
| **AVANT** | aucun incident observé : système nominal |
| **PENDANT** | dernier incident ouvert : détecté, en remédiation, ou en échec / escalade (`remediation_failed`) |
| **APRÈS** | dernier incident clos par une vérification `verify_tx` **OK** (`remediation_verified`) |

Une vérification en échec ne fait **jamais** passer en APRÈS. Un nouvel incident après un APRÈS repasse en PENDANT.

## 3. Interfaces consommées

Une seule : le **flux SSE du moteur de remédiation**, `GET http://remediation:8005/stream` (docs/contracts.md : « SSE/WebSocket -> Dashboard »). Le navigateur n'appelle jamais `remediation:8005` directement : il ouvre `<VITE_REMEDIATION_BASE>/stream` (défaut `/remediation/stream`), proxifié par Vite en dev et par nginx en prod.

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
| `REMEDIATION_PROXY_TARGET` | dev | `http://localhost:8005` | Cible du proxy Vite pour `/remediation` |
| `REMEDIATION_UPSTREAM` | runtime (conteneur) | `remediation:8005` | Hôte:port du moteur pour le proxy nginx |
| `REMEDIATION_AUTH_HEADER` | runtime | _vide_ | Valeur complète du header `Authorization` injecté par nginx (ex. `Bearer <token SOPS>`). Vide = aucun header |
| `DNS_RESOLVER` | runtime | `127.0.0.11` | Résolveur DNS Docker (résolution paresseuse de `remediation`) |

## 5. Exécution et exposition

- Dev : `npm run dev` sur le port **5174** (strict).
- Prod : conteneur nginx non-root écoutant **8080**, réseau `app` (doit joindre `remediation:8005`). nginx sert le statique **et** proxifie **uniquement** `GET /remediation/stream` (SSE : `proxy_buffering off`, timeout 1 h) ; `/remediation/*` autre renvoie 404. L'API `/events` du moteur n'est jamais atteignable depuis le navigateur. Healthcheck : `GET /healthz`.
- Le build utilise `base: './'` : l'app peut être servie à la racine d'un hôte ou sous un sous-chemin (dans ce cas régler `VITE_REMEDIATION_BASE` au build en conséquence).

## 6. Sécurité

- Le moteur de remédiation reste **hors réseau `edge`** ; le dashboard n'y accède que par le proxy nginx en lecture seule. Le jeton éventuel est injecté côté serveur (variable d'environnement du conteneur, fournie via SOPS), **jamais dans le bundle**.
- **Le dashboard ne doit pas être publié publiquement sans contrôle d'accès** : toute personne qui l'atteint peut lire le flux de supervision. Options : publier sur l'hôte en `127.0.0.1` / réseau d'admin, ou le router via le WAF avec authentification.
- Image multi-stage, utilisateur `nginx`, CSP stricte (`default-src 'self'`, `connect-src 'self'`), `X-Frame-Options: DENY`, `nosniff`, `server_tokens off`, conf générée dans `/tmp` (compatible `read_only: true` + `tmpfs: /tmp`, `cap_drop: [ALL]`, `no-new-privileges`).
- Liens Grafana : `rel="noopener noreferrer"`.

## 7. Tests (Vitest + Testing Library)

Parsing d'un AnomalyEvent conforme au contrat (exemple verbatim §3, énumération `incident_type`, cas invalides), parsing des messages du flux, reducer et timeline (4 étapes, échecs), MTTD/MTTR, **garde AVANT / PENDANT / APRÈS** (logique et rendu `aria-current`), composants clés, hook SSE (EventSource simulé : états, rejets, fermeture), rejeu de bout en bout d'un incident `service_flood`. Lancement : `npm run test`.
