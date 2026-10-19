"""Câblage compose du detector : l'URL de remédiation doit être l'endpoint complet.

Le detector POSTe tel quel sur REMEDIATION_URL (ml/detector/core.py) et le moteur
n'écoute que POST /events : une URL sans chemin ferait tomber chaque événement en 404
et casserait la boucle Zero-Touch sans erreur visible au démarrage.
"""

import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[3] / "infra" / "compose" / "docker-compose.yml"


def _service_block(text: str, name: str) -> str:
    m = re.search(rf"^  {name}:\n(.*?)(?=^  \S|\Z)", text, re.S | re.M)
    assert m, f"service {name} absent du compose"
    return m.group(1)


def test_detector_posts_to_remediation_events_endpoint():
    block = _service_block(COMPOSE.read_text(encoding="utf-8"), "detector")
    url = re.search(r"REMEDIATION_URL:\s*(\S+)", block)
    assert url, "REMEDIATION_URL non défini pour le detector"
    assert url.group(1).endswith("/events"), url.group(1)
