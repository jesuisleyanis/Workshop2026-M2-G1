#!/usr/bin/env python3
"""seed.py — peuple la base avec des utilisateurs et comptes FICTIFS.

Idempotent : relançable sans doublon. Crée les comptes de test utilisés par
verify_tx et la démo. Aucune donnée réelle.

Peut fonctionner de deux manières :
  - via l'API (par défaut) : register + création de comptes à travers les services ;
  - en direct SQL si DATABASE_URL est fourni (utilisé par les tests / le reset).
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "https://localhost")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# Jeu de comptes fictifs (username, password, iban_fake, solde initial en centimes).
FIXTURES = [
    ("demo01", "demo-pass-01", "FR-FAKE-0001", 1_000_00),
    ("demo02", "demo-pass-02", "FR-FAKE-0002", 500_00),
    ("ops",    "ops-pass-00",  "FR-FAKE-0003", 250_00),
]


def _post(path: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE_URL + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5, context=_CTX) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:  # 409 = déjà créé -> idempotent
        return exc.code, {}


def main() -> int:
    created = 0
    for username, password, iban, balance in FIXTURES:
        status, _ = _post(
            "/api/v1/register",
            {"username": username, "password": password, "iban_fake": iban, "balance_cents": balance},
        )
        if status in (200, 201):
            created += 1
        elif status == 409:
            pass  # déjà présent
        else:
            print(f"seed: échec pour {username} (HTTP {status})", file=sys.stderr)
    print(f"seed: {created} compte(s) créé(s), {len(FIXTURES)} au total (idempotent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
