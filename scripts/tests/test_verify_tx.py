"""Tests de verify_tx contre un faux payment-api HTTP local (aucune stack requise).

Le faux serveur valide chaque virement avec le VRAI schéma `TransactionIn` de payment-api :
un corps non conforme (ids en chaîne, `src_account` absent...) reçoit 422 comme en prod.
"""

import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_PATH = ROOT / "scripts" / "verify_tx"
_loader = importlib.machinery.SourceFileLoader("verify_tx", str(_PATH))  # pas d'extension .py
_spec = importlib.util.spec_from_loader("verify_tx", _loader)
vt = importlib.util.module_from_spec(_spec)
_loader.exec_module(vt)

pydantic = pytest.importorskip("pydantic")
_schemas_spec = importlib.util.spec_from_file_location(
    "payment_api_schemas", ROOT / "services/payment-api/src/payment_api/schemas.py"
)
schemas = importlib.util.module_from_spec(_schemas_spec)
sys.modules["payment_api_schemas"] = schemas  # pydantic résout les annotations différées
_schemas_spec.loader.exec_module(schemas)

USERS = {"demo01": ("demo-pass-01", 11), "demo02": ("demo-pass-02", 22), "ops": ("ops-pass-00", 33)}


class FakePaymentApi:
    """Auth + payment-api réduits : un compte par utilisateur, journal des requêtes."""

    def __init__(self):
        self.requests = []          # (méthode, chemin, corps, jeton)
        self.transactions = []      # plus récente en tête, comme l'API
        self.tx_status = "created"
        self.hide_new_tx = False

    def logins(self):
        return [body["username"] for m, path, body, _ in self.requests if path == "/api/v1/login"]

    def transfers(self):
        return [body for m, path, body, _ in self.requests
                if m == "POST" and path == "/api/v1/transactions"]

    def handle(self, method, path, body, token):
        self.requests.append((method, path, body, token))
        if path == "/api/v1/login":
            pwd, _ = USERS.get(body.get("username"), (None, None))
            if pwd is None or body.get("password") != pwd:
                return 401, {"error": "invalid_credentials"}
            return 200, {"access_token": f"tok-{body['username']}", "token_type": "bearer"}
        user = (token or "").removeprefix("tok-")
        if user not in USERS:
            return 401, {"error": "missing_token"}
        own = USERS[user][1]
        if path == "/api/v1/accounts":
            return 200, [{"id": own, "iban_fake": "FR-FAKE", "balance_cents": 1000, "currency": "EUR"}]
        if method == "GET":
            return 200, [t for t in self.transactions if own in (t["src_account"], t["dst_account"])]
        try:
            tx_in = schemas.TransactionIn.model_validate(body)
        except pydantic.ValidationError:
            return 422, {"error": "validation_error"}
        if tx_in.src_account != own:
            return 404, {"error": "account_not_found"}
        if tx_in.dst_account not in {acc for _, acc in USERS.values()}:
            return 404, {"error": "destination_not_found"}
        tx = {"id": 100 + len(self.transactions), **tx_in.model_dump(), "status": self.tx_status}
        if not self.hide_new_tx:
            self.transactions.insert(0, tx)
        return 201, tx


@pytest.fixture
def api(monkeypatch):
    fake = FakePaymentApi()

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            token = (self.headers.get("Authorization") or "").removeprefix("Bearer ") or None
            status, payload = fake.handle(method, self.path, body, token)
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._reply("GET")

        def do_POST(self):
            self._reply("POST")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fake.url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(vt, "BASE_URL", fake.url)
    monkeypatch.setattr(vt, "DST_ID", "")
    yield fake
    server.shutdown()
    server.server_close()


def test_sends_integer_ids_conforming_to_payment_api_schema(api):
    assert vt.main() == 0
    [body] = api.transfers()
    assert body == {"src_account": 11, "dst_account": 22, "amount_cents": vt.AMOUNT_CENTS}
    assert all(type(body[k]) is int for k in body)
    schemas.TransactionIn.model_validate(body)  # le vrai schéma accepte le corps


def test_former_iban_body_is_rejected_by_the_schema():
    """Non-régression I8 : l'ancien corps (IBAN en chaîne, sans source) vaut 422."""
    with pytest.raises(pydantic.ValidationError):
        schemas.TransactionIn.model_validate({"dst_account": "FR-FAKE-0002", "amount_cents": 100})


def test_destination_from_second_user_when_history_is_empty(api):
    assert vt.main() == 0
    assert api.logins() == ["demo01", "demo02"]


def test_destination_reused_from_history_avoids_a_second_login(api):
    api.transactions.append({"id": 1, "src_account": 33, "dst_account": 11,
                             "amount_cents": 5, "status": "created"})
    assert vt.main() == 0
    assert api.logins() == ["demo01"]
    assert api.transfers()[0]["dst_account"] == 33


def test_destination_from_env(api, monkeypatch):
    monkeypatch.setattr(vt, "DST_ID", "33")
    assert vt.main() == 0
    assert api.logins() == ["demo01"]
    assert api.transfers()[0]["dst_account"] == 33


def test_accepted_status_is_payment_api_created_status():
    models = (ROOT / "libs/python/resilience_db/src/resilience_db/models.py").read_text(encoding="utf-8")
    assert re.search(r'^\s*CREATED\s*=\s*"(\w+)"', models, re.M).group(1) == vt.CREATED


@pytest.mark.parametrize("setup", [
    lambda api, mp: mp.setattr(vt, "PASSWORD", "faux"),          # login 401
    lambda api, mp: mp.setattr(vt, "DST_ID", "999"),             # destination inconnue (404)
    lambda api, mp: mp.setattr(vt, "DST_ID", "pas-un-id"),       # configuration invalide
    lambda api, mp: setattr(api, "tx_status", "rejected"),       # statut inattendu
    lambda api, mp: setattr(api, "hide_new_tx", True),           # absente de l'historique
])
def test_any_failure_returns_1(api, monkeypatch, setup, capsys):
    setup(api, monkeypatch)
    assert vt.main() == 1
    assert capsys.readouterr().err.startswith("verify_tx: ")


def test_unreachable_service_returns_1(monkeypatch):
    monkeypatch.setattr(vt, "BASE_URL", "http://127.0.0.1:9")  # port fermé
    monkeypatch.setattr(vt, "TIMEOUT", 1.0)
    assert vt.main() == 1


def test_exit_codes_when_run_as_a_script(api):
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERIFY_")}
    env.update(BASE_URL=api.url, PYTHONIOENCODING="utf-8")
    ok = subprocess.run([sys.executable, str(_PATH)], env=env, capture_output=True, timeout=30)
    assert ok.returncode == 0, ok.stderr
    ko = subprocess.run([sys.executable, str(_PATH)], env={**env, "VERIFY_PASSWORD": "faux"},
                        capture_output=True, timeout=30)
    assert ko.returncode == 1
