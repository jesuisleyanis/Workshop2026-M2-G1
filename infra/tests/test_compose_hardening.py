"""Contrat de durcissement du Compose (vérifiable sans Docker).

Complète `security/hardening/audit.sh` sur les points qui ont cassé en live ou qui sont
sondés par le jury : Postgres sous `cap_drop: ALL` (ticket #11), moindre privilège partout.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "infra" / "compose" / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


def test_postgres_runs_as_non_root_so_cap_drop_all_needs_no_cap_add() -> None:
    pg = SERVICES["postgres"]
    assert pg["cap_drop"] == ["ALL"]
    # L'entrypoint officiel ne fait chown/gosu (CHOWN, SETUID, SETGID, ...) que lancé en root :
    # démarré directement en uid 70 (postgres de l'image alpine), aucune capability n'est requise.
    uid = str(pg.get("user", "")).split(":")[0]
    assert uid.isdigit() and int(uid) >= 1, "postgres doit démarrer non-root (user: \"70:70\") ou déclarer un cap_add minimal"
    assert "cap_add" not in pg, "non-root : aucun cap_add nécessaire (moindre privilège)"


def test_no_service_adds_capabilities_without_justification() -> None:
    # Toute capability ajoutée doit être une exception documentée dans hardening.md.
    doc = (ROOT / "security" / "hardening" / "hardening.md").read_text(encoding="utf-8")
    for name, svc in SERVICES.items():
        for cap in svc.get("cap_add", []):
            assert cap in doc and name in doc, f"{name}: cap_add {cap} non documenté dans hardening.md"


def test_hardening_anchor_applied_to_every_demo_service() -> None:
    # Hors profils optionnels lourds (ollama), chaque service porte l'ancre (no-new-privileges + cap_drop ALL).
    for name, svc in SERVICES.items():
        if name in {"ollama", "attacker"}:
            continue
        assert svc.get("cap_drop") == ["ALL"], f"{name}: cap_drop ALL manquant"
        assert "no-new-privileges:true" in svc.get("security_opt", []), f"{name}: no-new-privileges manquant"
