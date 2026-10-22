"""Proxy nginx du dashboard : aucun jeton de remédiation injecté sur une route d'ÉCRITURE.

Le nginx du dashboard détient le jeton de SERVICE (lectures : flux SSE, liste des IP bloquées). S'il
l'injectait aussi sur une route d'écriture, n'importe quel conteneur voisin ou processus local qui lui
parle écrirait dans le moteur sans aucun secret. Les écritures exigent le jeton OPÉRATEUR, saisi par
l'humain et seulement RELAYÉ (remediation/main.py `require_operator`). Vérifiable sans Docker.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (ROOT / "dashboard" / "docker" / "dashboard.conf.template").read_text(encoding="utf-8")
ENTRYPOINT = (ROOT / "dashboard" / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
SERVICES = yaml.safe_load(
    (ROOT / "infra" / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
)["services"]
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def locations() -> dict[str, str]:
    """{motif de location: corps} (accolades imbriquées gérées : limit_except, if)."""
    text = _strip_comments(TEMPLATE)
    out: dict[str, str] = {}
    for m in re.finditer(r"location\s+(.+?)\s*\{[ \t]*$", text, re.MULTILINE):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        out[m.group(1).strip()] = text[m.end():i - 1]
    return out


def _methods(body: str) -> set[str]:
    m = re.search(r"limit_except\s+([A-Z ]+?)\s*\{", body)
    return set(m.group(1).split()) if m else {"*"}


def remediation_routes() -> dict[str, str]:
    return {k: v for k, v in locations().items() if "/remediation/" in k and "proxy_pass" in v}


def write_routes() -> dict[str, str]:
    return {k: v for k, v in remediation_routes().items() if _methods(v) & (WRITE_METHODS | {"*"})}


def test_every_remediation_route_declares_its_methods():
    for loc, body in remediation_routes().items():
        assert "limit_except" in body, f"{loc} : méthodes non restreintes"


def test_write_routes_exist_and_never_inject_a_remediation_token():
    writes = write_routes()
    assert any("blocked-ips/" in loc for loc in writes), "route de déblocage absente du proxy"
    for loc, body in writes.items():
        assert "REMEDIATION_AUTH_HEADER" not in body, f"{loc} : jeton de service injecté sur une écriture"
        assert not re.search(r"Bearer", body, re.IGNORECASE), f"{loc} : Bearer en dur"
        # L'en-tête Authorization, s'il est fixé, ne peut être que celui du client (jeton opérateur).
        for value in re.findall(r"proxy_set_header\s+Authorization\s+([^;]+);", body):
            assert value.strip() == "$http_authorization", f"{loc} : Authorization={value!r}"


def test_write_routes_keep_the_anti_csrf_guard():
    # En-tête personnalisé ou JSON obligatoire : une page tierce déclenche un pré-vol CORS (jamais servi).
    for loc, body in write_routes().items():
        assert ("$http_x_resilience_dashboard" in body) or ("application/json" in body), loc


def test_read_routes_are_get_only():
    for loc, body in remediation_routes().items():
        if "REMEDIATION_AUTH_HEADER" in body:
            assert _methods(body) == {"GET"}, f"{loc} : jeton de service hors lecture"


def test_unknown_remediation_paths_are_closed():
    assert "return 404" in locations()["/remediation/"]


def test_operator_token_never_reaches_the_dashboard_container():
    assert "REMEDIATION_OPERATOR_TOKEN" not in _strip_comments(TEMPLATE)
    assert "REMEDIATION_OPERATOR_TOKEN" not in ENTRYPOINT
    assert "REMEDIATION_OPERATOR_TOKEN" not in str(SERVICES["dashboard"].get("environment", {}))
    # envsubst à liste fermée : $http_authorization reste une variable nginx, jamais substituée.
    assert "${http_authorization}" not in ENTRYPOINT
    holders = {name for name, svc in SERVICES.items()
               if "REMEDIATION_OPERATOR_TOKEN" in str(svc.get("environment", {}))}
    assert holders == {"remediation"}
