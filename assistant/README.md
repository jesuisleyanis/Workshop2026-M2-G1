# assistant - Assistant opérateur RAG (R9)

Assistant **documentaire en lecture seule** : il répond aux questions de l'opérateur (« que s'est-il passé ? », « quelle procédure pour `service_flood` ? ») à partir de `docs/`, de la table de décision et du journal d'incidents, avec **sources citées**.

> **FRONTIÈRE DE SÉCURITÉ.** L'assistant n'est **pas** le moteur de remédiation. Il ne déclenche **aucune action**, n'a **aucun accès privilégié** (ni socket Docker, ni Ansible, ni token de remédiation, ni appel au moteur) et n'est **pas dans la boucle de reprise**. Seule `remediation/` agit. Détails et preuves (tests négatifs) : [`CAHIER-DES-CHARGES.md`](CAHIER-DES-CHARGES.md) §2.

## Architecture

```
 docs/**/*.md ────────────┐
 remediation/decision_table.yml ─┼─(lecture seule, :ro)─► app.indexer ─► chunks ─► embeddings ─► Chroma (volume /data/chroma)
 incidents.json (export) ─┘                                                                         │
                                                                                                   ▼
 Opérateur ─► UI (/) ─► POST /api/v1/ask ─► retrieve top-k (Chroma) ─► prompt ─► Ollama (OLLAMA_BASE_URL) ─► {answer, sources}
                                                      └────── si Ollama KO : mode dégradé, passages seuls ──────┘
```

| Fichier | Rôle |
|---|---|
| `app/loader.py` | Charge `.md`, `decision_table.yml` (1 règle = 1 doc), journal d'incidents (1 incident = 1 doc) ; découpe par titres Markdown puis par taille |
| `app/embeddings.py` | Embeddings `hash` (défaut, local) ou `ollama` |
| `app/store.py` / `app/indexer.py` | Chroma persistant ; indexation (rebuild complet, idempotent) + CLI |
| `app/rag.py` | Récupération (testable sans LLM), prompt, génération |
| `app/llm.py` | `ChatOllama` + sonde de joignabilité |
| `app/main.py` | API FastAPI, middleware logs/`request_id`, erreurs au format du contrat |
| `app/static/` | UI (HTML + JS + CSS, sans inline) |

**Embeddings : `hash` par défaut** (lexical, déterministe, sans torch, fonctionne même sans Ollama). `EMBEDDINGS_BACKEND=ollama` pour du sémantique (`nomic-embed-text`) ; changer de backend impose de ré-indexer. Justification : CDC §5.

## Lancement en local (sans Docker)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ../libs/python/resilience_common -r requirements-dev.txt

# 1) indexer (chemins locaux, adapter si besoin)
export CHROMA_PATH=./.chroma
python -m app.indexer --docs-dir ../docs --decision-table ../remediation/decision_table.yml --incidents ./incidents.json

# 2) lancer l'API (Ollama sur la machine locale ou le PC IA)
export OLLAMA_BASE_URL=http://localhost:11434 OLLAMA_MODEL=qwen2.5:7b
uvicorn app.main:app --port 8006
# UI : http://localhost:8006/     Doc API : http://localhost:8006/docs
```

Préparer le modèle (une fois, **sur la machine qui héberge Ollama**, avec réseau) : `ollama pull qwen2.5:7b` (ou `llama3.1:8b`). Avec `EMBEDDINGS_BACKEND=ollama` : `ollama pull nomic-embed-text` aussi.

Exemple :

```bash
curl -s localhost:8006/api/v1/ask -H 'content-type: application/json' \
  -d '{"question":"Quelle procédure pour un incident service_flood ?"}'
# {"answer":"...","sources":[{"doc":"runbooks/service_flood.md","extrait":"...","section":"...","kind":"doc","score":0.45}],"degraded":false,"model":"qwen2.5:7b"}
```

## Docker

Le **contexte de build est la racine du repo** (la lib `resilience_common` est hors de `assistant/`) :

```bash
docker build -f assistant/Dockerfile -t resilience/assistant .
```

Snippet à intégrer dans `infra/compose/` par son propriétaire (non modifié ici) :

```yaml
  assistant:
    profiles: ["ai"]
    build: { context: ../.., dockerfile: assistant/Dockerfile }
    environment:
      OLLAMA_BASE_URL: ${OLLAMA_BASE_URL:-http://ollama:11434}   # ou http://<IP-PC-IA>:11434
      OLLAMA_MODEL: ${OLLAMA_MODEL:-qwen2.5:7b}
      FRAME_ANCESTORS: ${DASHBOARD_ORIGIN:-}                      # origine du dashboard (iframe)
    volumes:
      - ../../docs:/data/docs:ro
      - ../../remediation/decision_table.yml:/data/remediation/decision_table.yml:ro
      - incidents-export:/data/incidents:ro        # export JSON du journal (copie), jamais l'API du moteur
      - assistant-chroma:/data/chroma              # seul volume en écriture
    networks: [app]                                 # pas de ports publiés, pas sur `edge`
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    mem_limit: 1g
    healthcheck: { test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8006/health',timeout=3)"], interval: 30s }
  # + volumes: assistant-chroma, incidents-export
```

Le volume `/data/chroma` est **obligatoire** quand `read_only: true` (sans lui, Chroma ne peut pas écrire : `/ready` répond 503 et `assistant_store_error` est journalisé). Image construite et testée : ~870 Mo (chromadb + onnxruntime), `python:3.12-slim`, non-root uid 10001.

Au premier démarrage, si l'index est vide et que des sources existent, l'assistant **s'indexe tout seul** (`AUTO_INDEX=true`). Pour ré-indexer après de nouveaux incidents/docs :

```bash
docker compose exec assistant python -m app.indexer        # reconstruit l'index (rebuild complet)
```

(puis redémarrer le service pour que le client Chroma ouvert relise la collection : `docker compose restart assistant`).

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | URL d'Ollama (local, conteneur ou **PC IA**) |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Modèle de génération (<= 8B : `qwen2.5:7b`, `llama3.1:8b`) |
| `OLLAMA_TIMEOUT_S` / `OLLAMA_PROBE_TIMEOUT_S` | `120` / `2` | Timeout génération / sonde `/ready` |
| `EMBEDDINGS_BACKEND` | `hash` | `hash` (local) ou `ollama` |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Si backend `ollama` |
| `CHROMA_PATH` / `CHROMA_COLLECTION` | `/data/chroma` / `resilience_knowledge` | Persistance Chroma |
| `DOCS_DIR` | `/data/docs` | Dossier `docs/` (montage `:ro`) |
| `DECISION_TABLE_PATH` | `/data/remediation/decision_table.yml` | Table de décision |
| `INCIDENTS_PATH` | `/data/incidents/incidents.json` | Export du journal d'incidents (optionnel ; JSON liste, `{"incidents":[...]}` ou JSONL) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `900` / `120` | Découpage |
| `RAG_TOP_K` / `RAG_MIN_SCORE` | `4` / `0.05` | Passages retournés / seuil de similarité cosinus |
| `MAX_QUESTION_CHARS` | `1000` | Longueur max de la question |
| `AUTO_INDEX` | `true` | Indexe au démarrage si l'index est vide |
| `FRAME_ANCESTORS` | _(vide)_ | Origines autorisées à embarquer l'UI en iframe (CSP) |
| `METRICS_ENABLED` | `true` | Expose `/metrics` |

## Pointer vers le PC IA (Ollama déporté)

1. Sur le **PC IA** : `OLLAMA_HOST=0.0.0.0:11434 ollama serve` puis `ollama pull qwen2.5:7b`. Ouvrir le port 11434 **uniquement vers l'hôte de la stack** (pare-feu), réseau `RESILIENCE-G1`.
2. Sur l'hôte de la stack : `OLLAMA_BASE_URL=http://<IP-PC-IA>:11434` (dans `.env` ou l'environnement compose).
3. Contrôle : `curl localhost:8006/ready` -> `"ollama": {"reachable": true}` et `"mode": "nominal"`. Si le PC IA est éteint : `"mode": "degraded"`, l'assistant continue de renvoyer les passages pertinents.

Ollama n'est jamais exposé par le WAF ; seul l'assistant l'appelle.

## UI et intégration au dashboard

**Choix : page servie par l'assistant** (`GET /`), embarquée dans le dashboard comme **onglet via une iframe**. Raisons : une seule source de vérité, zéro build front supplémentaire, aucun CORS (la page appelle `/api/v1/ask` en relatif), isolation (CSP, pas de HTML injecté : tout est rendu par `textContent`).

Côté dashboard (à faire par son propriétaire ; `dashboard/` non modifié ici), onglet « Assistant » :

```tsx
// .env du dashboard : VITE_ASSISTANT_URL=/assistant/    (via le reverse-proxy interne) ou http://localhost:8006/ en dev
export function AssistantTab() {
  return <iframe title="Assistant opérateur" src={import.meta.env.VITE_ASSISTANT_URL}
                 className="h-full w-full border-0" sandbox="allow-scripts allow-same-origin allow-forms" />;
}
```

L'origine du dashboard doit figurer dans `FRAME_ANCESTORS` (sinon l'iframe est refusée par la CSP). L'API de l'assistant (`:8006`) n'est **pas** publiée sur `edge` : en démo, l'onglet passe par le reverse-proxy du dashboard/WAF (`/assistant/` -> `assistant:8006`). **Pas d'authentification applicative dans l'assistant** (service interne en lecture seule, réseau `app`) ; si l'on l'expose via le WAF, l'authentification doit être appliquée à ce niveau.

## Logs, métriques, sondes

- Logs JSON du contrat (`service: "assistant"`), `request_id` (reprend `X-Request-ID` ou en génère un). Événements émis : `assistant_index_built`, `assistant_index_empty`, `assistant_store_error`, `assistant_http_request`, `assistant_question_answered`, `assistant_llm_unavailable`. Ces noms sont **déclarés dans `docs/contracts.md §1`** et dans `resilience_common.RESERVED_EVENTS` ; `test_event_contract.py` échoue si l'assistant en émet un hors contrat. Ils ne sont pas utilisés par les règles d'alerte SOC.
- `/metrics` : `resilience_http_requests_total`, `resilience_http_request_duration_seconds`.
- `GET /health` (liveness), `GET /ready` (200 si Chroma chargé et non vide ; Ollama sondé, absence tolérée -> `mode: "degraded"`).
- Erreurs : `{"error": {"code", "message", "request_id"}}`.

## Tests

```bash
python3 -m venv /tmp/rc-assist && /tmp/rc-assist/bin/pip install -e ../libs/python/resilience_common -r requirements-dev.txt
cd assistant && /tmp/rc-assist/bin/python -m pytest -q
```

Aucun accès réseau : Ollama est mocké, `/ready` sonde un faux Ollama, corpus de fixtures dans `tests/fixtures/`.

| Fichier | Couvre |
|---|---|
| `tests/test_indexing.py` | chunks produits, Chroma peuplé et persistant, ré-indexation idempotente, sources optionnelles |
| `tests/test_retrieval.py` | bons passages pour une question donnée, **sans LLM** |
| `tests/test_api.py` | `/ask` -> `{answer, sources}` (LLM mocké), mode dégradé, `/health`, `/ready`, erreurs |
| `tests/test_security_guard.py` | **test négatif** : aucun endpoint d'action, aucune capacité d'exécution, conteneur non-root |

## Limites connues

- Embeddings `hash` : pas de synonymes (voir CDC §5) ; passer à `ollama` si le rappel est insuffisant.
- Le journal d'incidents est un **export** : à régénérer puis ré-indexer pour voir les incidents récents.
- Pas de mémoire de conversation : chaque question est indépendante.
- La qualité de la synthèse dépend du modèle 7B ; les `sources` permettent toujours de vérifier.
