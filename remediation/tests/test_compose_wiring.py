"""Câblage compose de la boucle de vérification (ROADMAP I15).

verify_tx est la preuve de reprise : si le conteneur remediation ne le trouve pas, ne
joint pas le WAF ou si les comptes fictifs n'ont aucun solde, chaque remédiation finit
en échec sans erreur visible au démarrage.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infra" / "compose" / "docker-compose.yml"
DOCKERFILE = ROOT / "remediation" / "Dockerfile"


def _service_env(name: str) -> dict[str, str]:
    text = COMPOSE.read_text(encoding="utf-8")
    block = re.search(rf"^  {name}:\n(.*?)(?=^  \S|\Z)", text, re.S | re.M)
    assert block, f"service {name} absent du compose"
    return {k: v.strip('"') for k, v in re.findall(r"^\s{6}([A-Z_]+):\s*(\S+)", block.group(1), re.M)}


def test_verify_tx_is_shipped_in_the_image_at_the_configured_path():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    path = re.search(r"VERIFY_TX_PATH=(\S+)", dockerfile).group(1)
    assert re.search(rf"COPY\b.*scripts/verify_tx\s+{re.escape(path)}\s*$", dockerfile, re.M)
    # le compose ne doit pas pointer ailleurs que là où l'image le dépose
    assert _service_env("remediation").get("VERIFY_TX_PATH", path) == path


def test_verify_tx_targets_the_waf_from_inside_the_network():
    base_url = _service_env("remediation").get("BASE_URL", "")
    assert base_url.startswith("https://waf:"), base_url


def test_seeded_accounts_have_a_balance():
    assert int(_service_env("auth").get("REGISTER_INITIAL_BALANCE_CENTS", "0")) > 0
