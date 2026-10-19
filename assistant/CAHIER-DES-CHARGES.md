# Cahier des charges - Assistant opérateur RAG (R9)

> Exigence **R9** du sujet (§3.3, pilier IA/DATA) : *assistant local RAG (Ollama + LangChain, modèle <= 8B), séparé de l'automate.*
> Composant **obligatoire**. Contrats transverses : [`docs/contracts.md`](../docs/contracts.md).

## 1. Objectif

Aider un opérateur à **comprendre et consulter** : « que s'est-il passé ? », « quelle est la procédure pour un incident `service_flood` ? », « quel est le RTO du PRA ? ».
Il répond **uniquement à partir de la documentation indexée** et **cite ses sources**.

## 2. FRONTIÈRE ASSISTANT / AUTOMATE (point dur, sondé par le jury)

| | **Moteur de remédiation** (`remediation/`) | **Assistant RAG** (`assistant/`) |
|---|---|---|
| Rôle | **Agit** : bloque une IP, redémarre un service, restaure un dump | **Explique** : lit des documents, répond à des questions |
| Décision | Table de décision + modèle ML (automatique, zero-touch) | Aucune. Ne décide rien, ne recommande pas d'exécuter quoi que ce soit |
| Accès système | Via `docker-socket-proxy` (verbes limités), Ansible, API authentifiée | **Aucun** : pas de socket Docker, pas d'Ansible, pas de shell, pas de token de remédiation |
| Entrées | Événements d'anomalie (`POST /events`, token SOPS) | Questions en langage naturel (`POST /api/v1/ask`) |
| Sorties | Actions + logs `remediation_*` | Texte + sources (lecture seule) |
| Dans la boucle de reprise | **Oui** (c'est la boucle) | **Non, jamais** : la démo de reprise fonctionne identiquement si l'assistant est arrêté |

**Garanties de conception (vérifiées par des tests automatiques, `tests/test_security_guard.py`) :**

1. **Aucun endpoint d'action.** Les seules routes sont `GET /health`, `GET /ready`, `GET /` (UI) et `POST /api/v1/ask`. Un test échoue si une route est ajoutée sans revue, et vérifie que `restart`, `block`, `restore`, `remediate`, `events`, `reindex`... renvoient 404/405.
2. **Aucune capacité d'exécution.** Le code n'importe ni `docker`, ni `subprocess`, ni `ansible`, ni `paramiko` ; aucun `os.system` ; aucun outil/agent LangChain (`bind_tools`, `create_react_agent`) : le LLM ne fait que **générer du texte**.
3. **Aucun secret ni accès privilégié.** Le service ne reçoit ni token de remédiation, ni URL du moteur, ni socket Docker, ni clé SOPS. Conteneur non-root, `cap_drop: ALL`, `read_only`, sources montées en **lecture seule** (`:ro`).
4. **Lecture seule des données.** Il lit `docs/*.md`, `remediation/decision_table.yml` et un **export JSON** du journal d'incidents (copie, pas d'accès à l'API du moteur). Il n'écrit que dans son propre index Chroma (volume dédié).
5. **Pas d'auto-ré-indexation par API.** L'indexation est une commande d'exploitation (CLI), pas un endpoint, pour ne pas ajouter de surface.
6. **Prompt défensif.** Le prompt système interdit d'inventer, rappelle l'absence d'accès au système et traite le contexte comme donnée (anti prompt-injection documentaire). Même si le modèle était manipulé, il n'a **aucun moyen** d'agir : la frontière est architecturale, pas seulement textuelle.

> Une demande du type « redémarre payment-api » reçoit une réponse **textuelle** (explication de la procédure documentée, rappel que seul le moteur agit) ; aucune action n'est déclenchée.

## 3. Exigences fonctionnelles

| ID | Exigence | Réalisation |
|---|---|---|
| F1 | Modèle local Ollama <= 8B | `OLLAMA_MODEL` (défaut `qwen2.5:7b` ; alternative `llama3.1:8b`), `OLLAMA_BASE_URL` (défaut `http://ollama:11434`), déployable sur le **PC IA** distant |
| F2 | RAG LangChain + Chroma | `langchain-chroma` (persistant), `langchain-text-splitters`, `langchain-ollama`, `ChatPromptTemplate` |
| F3 | Corpus | `docs/**/*.md` (runbooks, PCA/PRA, architecture, contrats), `remediation/decision_table.yml`, journal d'incidents exporté (JSON/JSONL, optionnel ; producteur : `remediation/export_journal.py`, volume `incidents-export`) |
| F4 | `POST /api/v1/ask {question}` -> `{answer, sources:[{doc, extrait}]}` | + champs additifs `degraded`, `model`, et par source `section`, `kind`, `score` |
| F5 | `GET /health`, `GET /ready` | `/ready` = index Chroma chargé et non vide. Ollama est sondé mais **toléré absent** (mode dégradé) |
| F6 | Logs contrat §1 | `resilience_common.get_logger("assistant")`, `request_id`, `duration_ms`, `http_*` |
| F7 | Métriques contrat §2 | `/metrics` via `resilience_common.metrics.instrument` (`resilience_http_*`) |
| F8 | UI simple | Page servie par l'assistant (`/`), embarquable en onglet du dashboard (iframe) |

### Mode dégradé (documenté)

- **Ollama injoignable / timeout / modèle absent** : `/ask` répond `200` avec `degraded: true`, un message explicite, et **les passages documentaires pertinents** dans `sources` (la recherche fonctionne sans LLM). `/ready` reste `200` avec `mode: "degraded"`.
- **Index vide, illisible, ou embeddings différents de la configuration** : `/ready` et `/ask` répondent `503` (`index_not_ready`) avec la marche à suivre.

## 4. Exigences non fonctionnelles

- **Sécurité** : voir §2. Image `python:3.12-slim`, multi-stage, utilisateur non-root (uid 10001), pas de curl (healthcheck stdlib), télémétrie Chroma désactivée, en-têtes `CSP` (`frame-ancestors`), `nosniff`, UI sans `innerHTML` ni script inline.
- **Hors-ligne** : aucune dépendance à Internet à l'exécution (embeddings locaux par défaut, modèle Ollama pré-téléchargé).
- **Ressources** : l'assistant seul est léger (pas de torch). Le coût RAM est celui du modèle Ollama (~5-6 Go pour un 7B quantifié) -> à déporter sur le PC IA si la RAM est serrée.
- **Données** : exclusivement fictives ; les questions ne sont pas journalisées (seulement leur longueur), pour ne pas stocker de contenu saisi libre dans Loki.
- **Tests** : `pytest`, aucun accès réseau (Ollama mocké), corpus de fixtures.

## 5. Choix d'embeddings (justification)

Défaut `hash` : hashing lexical déterministe (tokens sans accents, snake_case éclaté, bigrammes, normalisation L2) - **zéro dépendance lourde**, instantané, hors-ligne, et surtout **indépendant d'Ollama** : la recherche documentaire marche même en mode dégradé. Adapté à un corpus d'identifiants techniques (`service_flood`, `restore_pg_dump`).
Alternative `ollama` (`nomic-embed-text`) : meilleur rappel sémantique (synonymes, paraphrases) au prix d'une dépendance à Ollama pour indexer **et** chaque question. `sentence-transformers` a été écarté (torch ~2 Go, image trop lourde pour un gain marginal ici).
**Limite assumée** : le backend `hash` ne comprend pas les synonymes (« panne » vs « indisponibilité »). Le nom du backend est stocké dans la collection ; un changement impose une ré-indexation (détecté par `/ready`).

## 6. Hors périmètre

Déclenchement ou simulation d'actions, authentification applicative (l'accès est contrôlé par l'exposition réseau, voir README), mémoire de conversation, fine-tuning, ingestion de PDF/PPTX (`docs/sujet/`), interrogation en direct de Loki/Prometheus.

## 7. Critères d'acceptation

- [x] `pytest` vert (indexation, récupération sans LLM, `/ask` avec Ollama mocké, garde de sécurité).
- [x] `/ready` 200 avec Ollama absent (mode dégradé), 503 si index vide.
- [x] Aucun endpoint d'action ; aucune capacité d'exécution (tests négatifs).
- [x] Intégration compose (profil `ai`, réseau `app`, `read_only`, volumes `/data/*`) et onglet dashboard (iframe `/assistant/` proxifiée par le nginx du dashboard) : voir README.
