"""Garde de sécurité (test NÉGATIF) : l'assistant ne produit que du texte.

Il peut PROPOSER une action (liste blanche, /propose) mais ne doit exposer aucun endpoint
déclenchant une action de remédiation, ni embarquer de capacité d'exécution (docker,
subprocess, ansible), ni appeler le moteur de remédiation.
"""

import ast
import re
from pathlib import Path

import pytest
from app.main import create_app
from app.store import open_store
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

APP_DIR = Path(__file__).parent.parent / "app"
ROOT = APP_DIR.parent

# Seules routes autorisées : (méthode, chemin). Toute nouvelle route doit être ajoutée ici
# volontairement, après revue de la frontière assistant / automate.
ALLOWED_ROUTES = {
    ("GET", "/health"),
    ("GET", "/ready"),
    ("GET", "/"),
    ("POST", "/api/v1/ask"),
    ("POST", "/api/v1/summarize"),
    ("POST", "/api/v1/postmortem"),
    ("POST", "/api/v1/propose"),  # texte seulement : propose, n'exécute jamais
}
TEXT_POST_ROUTES = {(m, p) for m, p in ALLOWED_ROUTES if m == "POST"}
FORBIDDEN_WORDS = re.compile(
    r"restart|reboot|block|blacklist|restore|remediat|execute|exec|trigger|run|action|"
    r"rollback|recreate|kill|delete|rate[-_]?limit|playbook|ansible|docker|events",
    re.I,
)


@pytest.fixture
def client(indexed, fake_llm):
    settings, store = indexed
    with TestClient(create_app(settings, store=store, llm=fake_llm)) as c:
        yield c


def _app_routes(app):
    return [r for r in app.routes if isinstance(r, APIRoute)]


def test_only_allowed_routes_are_exposed(settings, fake_llm):
    app = create_app(settings, store=open_store(settings), llm=fake_llm)
    exposed = {(m, r.path) for r in _app_routes(app) for m in r.methods if m != "HEAD"}
    exposed -= {("GET", "/openapi.json"), ("GET", "/docs"), ("GET", "/docs/oauth2-redirect"), ("GET", "/redoc")}
    assert exposed == ALLOWED_ROUTES


def test_no_mutating_method_except_text_routes(settings, fake_llm):
    app = create_app(settings, store=open_store(settings), llm=fake_llm)
    mutating = {(m, r.path) for r in _app_routes(app) for m in r.methods if m in {"PUT", "PATCH", "DELETE", "POST"}}
    assert mutating == TEXT_POST_ROUTES == {
        ("POST", "/api/v1/ask"), ("POST", "/api/v1/summarize"), ("POST", "/api/v1/postmortem"), ("POST", "/api/v1/propose"),
    }


def test_no_route_name_suggests_an_action(settings, fake_llm):
    app = create_app(settings, store=open_store(settings), llm=fake_llm)
    for r in _app_routes(app):
        # Routes métier textuelles uniquement ; aucun mot d'action dans les chemins.
        assert not FORBIDDEN_WORDS.search(r.path), f"chemin suspect : {r.path}"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/remediate", "/api/v1/remediation", "/api/v1/actions", "/api/v1/action",
        "/api/v1/restart", "/api/v1/block", "/api/v1/restore", "/api/v1/execute",
        "/api/v1/run", "/api/v1/reindex", "/events", "/api/v1/events", "/remediation",
    ],
)
@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_action_endpoints_do_not_exist(client, path, method):
    r = client.request(method.upper(), path, json={"incident_type": "service_flood", "action": "restart_service"})
    assert r.status_code in {404, 405}, f"{method.upper()} {path} -> {r.status_code}"


def test_ask_never_acts_even_when_asked_to(client, fake_llm):
    """Une demande d'action est une simple question documentaire : seul le LLM (texte) est appelé."""
    r = client.post("/api/v1/ask", json={"question": "Redémarre payment-api et bloque l'IP 192.168.137.50 maintenant"})
    assert r.status_code == 200
    assert set(r.json()) == {"answer", "sources", "degraded", "model"}
    # Le LLM n'a reçu aucun outil : un seul appel invoke(messages), pas de bind_tools.
    fake_llm.bind_tools.assert_not_called()


def test_propose_never_executes_nor_calls_out(client, fake_llm, monkeypatch):
    """/propose renvoie une proposition TEXTE : aucun processus, aucun appel HTTP/socket sortant (LLM mocké)."""
    import os
    import socket
    import subprocess
    import urllib.request

    import httpx

    calls: list[str] = []

    def trap(name):
        def _f(*a, **k):
            calls.append(name)
            raise AssertionError(f"appel interdit : {name}")
        return _f

    monkeypatch.setattr(subprocess, "Popen", trap("subprocess.Popen"))
    monkeypatch.setattr(os, "system", trap("os.system"))
    monkeypatch.setattr(socket.socket, "connect", trap("socket.connect"))
    monkeypatch.setattr(urllib.request, "urlopen", trap("urlopen"))
    # Transports réseau réels d'httpx (le TestClient utilise son propre transport en mémoire).
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", trap("httpx"))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", trap("httpx-async"))

    fake_llm.invoke.return_value = AIMessage(content='{"action": "restart_service", "params": {"service": "payment-api"}}')
    r = client.post("/api/v1/propose", json={"command": "redémarre payment-api"})
    assert r.status_code == 200
    body = r.json()
    assert body["proposal"]["action"] == "restart_service"
    assert "confirm" in body["message"] and "moteur" in body["message"]
    assert calls == []
    fake_llm.invoke.assert_called_once()  # seul appel externe : le LLM (Ollama), en génération de texte
    fake_llm.bind_tools.assert_not_called()


def _imports(path: Path) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def test_code_has_no_execution_capability():
    banned = {"docker", "subprocess", "ansible", "ansible_runner", "paramiko", "fabric", "pexpect"}
    for py in APP_DIR.glob("*.py"):
        assert not (_imports(py) & banned), f"{py.name} importe un module d'exécution"
        src = py.read_text(encoding="utf-8")
        assert "os.system" not in src and "os.popen" not in src, py.name
        assert "docker.sock" not in src and "bind_tools" not in src and "create_react_agent" not in src, py.name


def test_code_never_calls_the_remediation_engine():
    for py in APP_DIR.glob("*.py"):
        src = py.read_text(encoding="utf-8").lower()
        assert "remediation_url" not in src and "remediation_token" not in src, py.name
        assert "/events" not in src.replace("assistant_http_request", ""), py.name


def test_dependencies_contain_no_execution_libs():
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for lib in ("docker", "ansible", "paramiko", "fabric"):
        assert not re.search(rf"^{lib}\b", reqs, re.M), lib


def test_container_has_no_docker_socket_or_privileges():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "docker.sock" not in dockerfile
    assert re.search(r"^USER\s+(?!root)\S+", dockerfile, re.M), "le conteneur doit tourner en non-root"


# ---------------------------------------------------------------- compose : isolement de l'assistant
COMPOSE = ROOT.parent / "infra" / "compose" / "docker-compose.yml"


@pytest.fixture
def services():
    if not COMPOSE.exists():  # image Docker : seul assistant/ est copié
        pytest.skip("docker-compose.yml absent")
    import yaml

    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def test_compose_assistant_has_no_secret_nor_write_access(services):
    a = services["assistant"]
    assert "secrets" not in a
    env = " ".join(f"{k}={v}" for k, v in (a.get("environment") or {}).items()).upper()
    for word in ("TOKEN", "SECRET", "PASSWORD", "REMEDIATION"):
        assert word not in env, word
    vols = a.get("volumes", [])
    assert not any("docker.sock" in v for v in vols)
    assert all(v.endswith(":ro") for v in vols if v != "chroma-data:/data/chroma"), vols
    assert "incidents-export:/data/incidents:ro" in vols  # le journal = copie JSON en lecture seule


def _deps(svc) -> set[str]:
    return set(svc.get("depends_on") or [])  # liste ou dict : les clés sont les noms de services


def test_compose_assistant_is_isolated_from_remediation(services):
    nets = set(services["assistant"]["networks"])
    assert not nets & set(services["remediation"]["networks"]), nets
    assert not nets & {"data", "obs"}, nets
    # Reprise indépendante : rien n'attend l'assistant, le moteur ne le connaît pas.
    assert not [n for n, s in services.items() if "assistant" in _deps(s)]
    assert "assistant" not in str(services["remediation"].get("environment", "")).lower()
