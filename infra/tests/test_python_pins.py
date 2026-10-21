"""Les services FastAPI épinglent le même FastAPI/pydantic que `resilience_common`.

`resilience_common.metrics.instrument` annote `/metrics` avec un `Response` importé
localement : FastAPI 0.115 ne sait pas le résoudre et l'app ne démarre plus. Un service
qui diverge (face-id l'a fait) casse donc au démarrage du conteneur, pas seulement en test.
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
