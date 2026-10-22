"""Les services à dépendances épinglées partagent la même pile FastAPI qu'auth.

face-id épinglait FastAPI 0.115 / pydantic 2.9 et tirait les libs du monorepo par leur nom
(introuvables sur PyPI : build cassé, et porte ouverte au *dependency confusion*). Les libs
s'installent depuis `libs/python/` en `--no-deps` : leurs dépendances doivent être épinglées.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "services" / "auth" / "requirements.txt"
FASTAPI_SERVICES = ["services/payment-api", "services/face-id"]


def _pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(fastapi|pydantic|uvicorn)(?:\[[^\]]*\])?==(\S+)", line.strip())
        if m:
            pins[m.group(1)] = m.group(2)
    return pins


@pytest.mark.parametrize("service", FASTAPI_SERVICES)
def test_fastapi_stack_pins_match_auth(service: str) -> None:
    reference = _pins(REFERENCE)
    assert set(reference) == {"fastapi", "pydantic", "uvicorn"}
    assert _pins(ROOT / service / "requirements.txt") == reference


@pytest.mark.parametrize("service", ["services/auth", *FASTAPI_SERVICES])
def test_monorepo_libs_are_never_resolved_from_pypi(service: str) -> None:
    text = (ROOT / service / "requirements.txt").read_text(encoding="utf-8")
    names = {re.split(r"[\[=<>~ ]", line.strip())[0].lower() for line in text.splitlines() if line.strip() and not line.startswith("#")}
    assert not names & {"resilience-common", "resilience-db", "resilience_common", "resilience_db"}
    assert {"sqlalchemy", "prometheus-client"} <= names, "dépendances runtime des libs (--no-deps) manquantes"
