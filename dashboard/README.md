# dashboard - Supervision RESILIENCE-ALPHA (React + Vite + TypeScript + Tailwind)

Console de supervision jury / opérateur (design « ZTR Supervision »), conçue pour être filmée : **AVANT / PENDANT / APRÈS**, score d'anomalie ML en direct et courbe 2 min par service, timeline détection -> décision -> action -> vérification, MTTD/MTTR, transaction de vérification, actions de remédiation, état des services, signaux dominants, playbooks, preuves Prometheus/Loki, liens Grafana. Onglet **Assistant** : UI de l'assistant RAG (lecture seule, profil compose `ai`) embarquée en iframe same-origin via `/assistant/`. Quoi et pourquoi : [`CAHIER-DES-CHARGES.md`](CAHIER-DES-CHARGES.md). Contrats : [`docs/contracts.md`](../docs/contracts.md).
## Lancement

```bash
cd dashboard
npm install
npm run mock      # terminal 1 : faux moteur de remédiation sur :8005 (optionnel)
npm run dev       # terminal 2 : http://localhost:5174
```

Déclencher un incident de démonstration : boutons **Répétition · déclencher** de la barre latérale (dev), ou `curl 'http://localhost:8005/trigger?type=service_flood'` (ou `auth_abuse`, `data_corruption`). `AUTO=40 npm run mock` en rejoue un toutes les 40 s. Avec le vrai moteur : `REMEDIATION_PROXY_TARGET=http://localhost:8005 npm run dev`.

**Sans aucun backend** : `VITE_STREAM_SOURCE=simulation npm run dev` (ou bouton « Passer en simulation ») — simulation locale, signalée à l'écran, qui émet les mêmes trames que le moteur. Port 5174 occupé : `npx vite --port 5175`.

## Scripts

| Commande | Effet |
|---|---|
| `npm run dev` | Dev server (port 5174, strict) ; `/remediation/*` proxifié vers `REMEDIATION_PROXY_TARGET`, `/assistant/*` vers `ASSISTANT_PROXY_TARGET` |
| `npm run build` | `tsc --noEmit` puis build Vite dans `dist/` |
| `npm run preview` | Sert `dist/` sur 5174 |
| `npm run lint` / `typecheck` | ESLint / typage |
| `npm run test` | Vitest en mode run (CI, non-watch) |
| `npm run test:watch` | Vitest en watch |
| `npm run mock` | Faux moteur SSE (dev / répétitions) |

## Variables d'environnement

| Variable | Défaut | Quand |
|---|---|---|
| `VITE_REMEDIATION_BASE` | `/remediation` | build : base du flux (`<base>/stream`) |
| `VITE_GRAFANA_BASE` | `http://localhost:3000` | build : liens Grafana et Explore |
| `VITE_STREAM_SOURCE` | `live` | build : `live` \| `auto` (bascule en simulation si flux injoignable) \| `simulation` |
| `VITE_LIVE_TRIGGERS` | _vide_ | build : `true` = déclencheurs en flux réel hors dev (mock uniquement) |
| `VITE_ASSISTANT_URL` | `/assistant/` | build : URL de l'UI de l'assistant (iframe, slash final requis) |
| `REMEDIATION_PROXY_TARGET` | `http://localhost:8005` | dev : cible du proxy Vite |
| `ASSISTANT_PROXY_TARGET` | `http://localhost:8006` | dev : cible du proxy Vite pour `/assistant` |
| `REMEDIATION_UPSTREAM` | `remediation:8005` | conteneur : upstream du proxy nginx |
| `ASSISTANT_UPSTREAM` | `assistant:8006` | conteneur : upstream nginx de l'assistant (relaie uniquement `GET /assistant/`, `GET /assistant/static/*`, `POST /assistant/api/v1/ask`) |
| `REMEDIATION_AUTH_HEADER` | _vide_ | conteneur : header `Authorization` injecté (ex. `Bearer ...`) |
| `DNS_RESOLVER` | `127.0.0.11` | conteneur : résolveur DNS |

## Architecture

```
src/
  main.tsx, App.tsx            source (réel / simulation), service suivi, déclencheurs, mise en page
  config.ts                    STREAM_URL, GRAFANA_BASE, STREAM_SOURCE, LIVE_TRIGGERS
  types/events.ts              AnomalyEvent (contrat §3), StreamMessage, Incident, DashboardState
  lib/
    parse.ts                   validation AnomalyEvent + messages SSE (Result ok/error)
    state.ts                   reducer, derivePhase, buildTimeline, MTTR, scoreLevel, PLAYBOOKS
    simulator.ts               SimulatedEventSource : flux local (mêmes trames que le moteur)
    format.ts                  durées, heures
  hooks/
    useRemediationStream.ts    EventSource : statut, validation, reconnexion (auto)
    useDashboard.ts            reducer + flux ; expose { state, phase, reset }
    useNow.ts                  horloge (compteur MTTR live)
  components/
    Sidebar                    état du flux, horloge, bascule de source, déclencheurs, Grafana
    PhaseBanner                AVANT / PENDANT / APRÈS (aria-current) + phrase d'état
    MetricsCards               ScoreCard, MTTD / MTTR (live), VerificationCard
    ScoreChart                 courbe 2 min par service, seuil, marqueurs détection / vérifié
    IncidentTimeline           4 cartes, statut textuel, décalages +N s
    IncidentDetails            ActionsPanel, SignalsPanel, PlaybooksPanel, EvidencePanel
    ServicesGrid               santé des services
    GrafanaLinks, Panel        liens Grafana / Explore ; carte, pastilles, tonalités
  test/                        setup, fixtures (exemple du contrat, séquence d'incident, FakeEventSource)
mock/remediation-mock.mjs      faux moteur SSE (hors image Docker)
docker/                        nginx.conf, dashboard.conf.template, security-headers.conf, entrypoint.sh
```

Flux de données : SSE -> `parseStreamMessage` (valide, sinon compte un rejet) -> `reducer` -> `derivePhase` / `buildTimeline` -> composants. Aucune logique de décision n'est dans l'écran : il reflète ce que le moteur publie.

## Tests

```bash
npm run test
```

- `lib/parse.test.ts` : AnomalyEvent conforme au contrat (exemple §3 verbatim, 5 `incident_type`, 10 cas invalides), messages du flux.
- `lib/state.test.ts` : phases AVANT/PENDANT/APRÈS (dont vérification KO, escalade, nouvel incident, reset), timeline, MTTD/MTTR (valeurs moteur + repli), score, robustesse.
- `components/components.test.tsx` : **garde d'affichage avant/pendant/après** (un seul `aria-current`, phrase d'état, badge zero-touch), timeline, carte de score, courbe (géométrie, onglets, marqueurs), indicateurs, vérification, services, actions, signaux, playbooks, preuves, liens Grafana.
- `hooks/useRemediationStream.test.tsx` : statuts SSE, messages valides/rejetés, fermeture au démontage.
- `App.test.tsx` : rejeu complet d'un incident, rejets visibles, reset, flux interrompu ; simulation locale jusqu'à APRÈS, bascule `auto`, bascule manuelle, déclencheur dev.

## Docker (prod)

```bash
docker build -t resilience-dashboard \
  --build-arg VITE_REMEDIATION_BASE=/remediation \
  --build-arg VITE_GRAFANA_BASE=http://192.168.137.1:3000 dashboard
docker run --rm --network <reseau-app> --read-only --tmpfs /tmp --cap-drop ALL \
  -e REMEDIATION_UPSTREAM=remediation:8005 -p 127.0.0.1:8081:8080 resilience-dashboard
```

Multi-stage `node:22-alpine` -> `nginx:1.27-alpine`, utilisateur `nginx`, port **8080**, `HEALTHCHECK` sur `/healthz`. La conf nginx est générée au démarrage (`envsubst`) dans `/tmp`.

### Câblage compose

- Service `dashboard` sur le réseau `app` (joint `remediation:8005`), `depends_on: remediation`.
- Publier avec précaution (le dashboard donne la vue d'ensemble du SI) : `127.0.0.1:<port>:8080` ou via le WAF **avec authentification**. Ne pas l'exposer librement sur `edge`.
- Token du moteur (si `/stream` est authentifié) : `REMEDIATION_AUTH_HEADER="Bearer <token>"` depuis SOPS, jamais en clair dans le compose.
- `VITE_GRAFANA_BASE` est ouvert par le navigateur du jury : mettre l'adresse atteignable depuis la machine de projection.
- Durcissement : `read_only: true`, `tmpfs: [/tmp]`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, limites CPU/RAM.
