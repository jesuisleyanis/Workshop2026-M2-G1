"""API : Ollama est MOCKÉ (aucune dépendance réseau)."""

from dataclasses import replace

import pytest
from app.main import create_app
from app.store import open_store
from fastapi.testclient import TestClient


@pytest.fixture
def client(indexed, fake_llm):
    settings, store = indexed
    with TestClient(create_app(settings, store=store, llm=fake_llm)) as c:
        yield c


def test_ask_returns_answer_and_sources(client, fake_llm):
    r = client.post("/api/v1/ask", json={"question": "Quelle procédure pour un incident service_flood ?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Réponse simulée [1]."
    assert body["degraded"] is False
    assert body["sources"], "sources attendues"
    first = body["sources"][0]
    assert first["doc"] == "runbook-service-flood.md"
    assert isinstance(first["extrait"], str) and first["extrait"]
    assert r.headers["x-request-id"]

    # Le LLM mocké a reçu la question ET le contexte récupéré (système + humain).
    fake_llm.invoke.assert_called_once()
    messages = fake_llm.invoke.call_args.args[0]
    human = messages[-1].content
    assert "service_flood" in human and "QUESTION" in human and "[1]" in human
    assert "AUCUN accès au système" in messages[0].content


def test_ask_degraded_mode_when_ollama_is_down(indexed, fake_llm):
    settings, store = indexed
    fake_llm.invoke.side_effect = ConnectionError("ollama injoignable")
    with TestClient(create_app(settings, store=store, llm=fake_llm)) as c:
        r = c.post("/api/v1/ask", json={"question": "Comment restaurer le dump Postgres ?"})
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is True
    assert "dégradé" in body["answer"].lower()
    assert body["sources"][0]["doc"] == "runbook-data-corruption.md"  # la recherche fonctionne sans LLM


def test_ask_without_relevant_passage_skips_llm(indexed, fake_llm):
    settings, store = indexed
    with TestClient(create_app(replace(settings, min_score=0.05), store=store, llm=fake_llm)) as c:
        r = c.post("/api/v1/ask", json={"question": "recette de la tarte aux pommes"})
    assert r.status_code == 200
    assert r.json()["sources"] == []
    fake_llm.invoke.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": "ab"}, {"q": "hello world"}])
def test_ask_validation_error_follows_contract(client, payload):
    r = client.post("/api/v1/ask", json=payload)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_request" and err["request_id"]


def test_ask_rejects_overlong_question(client):
    r = client.post("/api/v1/ask", json={"question": "x" * 1001})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "question_too_long"


def test_ask_503_when_index_is_empty(settings, fake_llm):
    store = open_store(settings)  # collection vide
    with TestClient(create_app(settings, store=store, llm=fake_llm)) as c:
        r = c.post("/api/v1/ask", json={"question": "service_flood ?"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "index_not_ready"


def test_health_is_always_ok(settings, fake_llm):
    with TestClient(create_app(settings, store=open_store(settings), llm=fake_llm)) as c:
        assert c.get("/health").json() == {"status": "ok", "service": "assistant"}


def test_ready_requires_loaded_chroma_but_tolerates_missing_ollama(client):
    r = client.get("/ready")  # sonde Ollama = False (fixture autouse)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready" and body["mode"] == "degraded"
    assert body["ollama"]["reachable"] is False
    assert body["chroma"]["chunks"] > 0


def test_ready_nominal_when_ollama_reachable(indexed, fake_llm, monkeypatch):
    monkeypatch.setattr("app.main.ollama_reachable", lambda _s: True)
    settings, store = indexed
    with TestClient(create_app(settings, store=store, llm=fake_llm)) as c:
        assert c.get("/ready").json()["mode"] == "nominal"


def test_ready_503_when_index_empty(settings, fake_llm):
    with TestClient(create_app(settings, store=open_store(settings), llm=fake_llm)) as c:
        r = c.get("/ready")
    assert r.status_code == 503 and r.json()["status"] == "not_ready"


def test_ready_503_when_embeddings_backend_changed(indexed, fake_llm):
    settings, store = indexed
    other = replace(settings, embeddings_backend="ollama", ollama_embed_model="nomic-embed-text")
    with TestClient(create_app(other, store=store, llm=fake_llm)) as c:
        r = c.get("/ready")
    assert r.status_code == 503 and "ré-indexer" in r.json()["chroma"]["detail"]


def test_auto_index_on_startup_builds_missing_index(settings, fake_llm):
    s = replace(settings, auto_index=True)
    with TestClient(create_app(s, llm=fake_llm)) as c:  # pas de store injecté : lifespan réel
        assert c.get("/ready").status_code == 200
        r = c.post("/api/v1/ask", json={"question": "Que s'est-il passé pour inc-0001 ?"})
    assert r.json()["sources"][0]["doc"] == "journal/inc-0001"


def test_ui_is_served_with_frame_policy(client):
    r = client.get("/")
    assert r.status_code == 200 and "Assistant opérateur" in r.text
    assert "frame-ancestors 'self'" in r.headers["content-security-policy"]
    assert client.get("/static/assistant.js").status_code == 200
    # chemins relatifs : la page reste fonctionnelle derrière le proxy /assistant/ du dashboard
    assert 'src="static/assistant.js"' in r.text and 'href="static/assistant.css"' in r.text
