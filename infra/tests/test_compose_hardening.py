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


def test_hardening_anchor_applied_to_every_service() -> None:
    # Chaque service porte l'ancre (no-new-privileges + cap_drop ALL), y compris `ollama` (#22).
    # Seul `attacker` (banc d'essai curl `sleep infinity`, profil `attack`) en est dispensé.
    for name, svc in SERVICES.items():
        if name == "attacker":
            continue
        assert svc.get("cap_drop") == ["ALL"], f"{name}: cap_drop ALL manquant"
        assert "no-new-privileges:true" in svc.get("security_opt", []), f"{name}: no-new-privileges manquant"


def test_image_tags_are_pinned_for_reproducibility() -> None:
    # R5 (reproductibilité, #21) : aucune image en `:latest` (un rebuild ne doit pas tirer un major différent).
    for name, svc in SERVICES.items():
        image = svc.get("image")
        if not image:
            continue  # service construit localement (build:)
        assert ":" in image, f"{name}: image {image!r} sans tag (= latest implicite)"
        tag = image.rsplit(":", 1)[1]
        assert tag != "latest", f"{name}: image épinglée en :latest (reproductibilité R5)"


def test_remediation_container_matches_read_only_claim() -> None:
    # CDC §5.4 : racine en lecture seule, seul point inscriptible = le volume journal (#22).
    rem = SERVICES["remediation"]
    assert rem.get("read_only") is True, "remediation doit être read_only (la CDC §5.4 l'affirme)"
    mounts = [v.split(":")[1] for v in rem["volumes"] if ":" in v]
    assert "/var/lib/remediation" in mounts, "volume journal /var/lib/remediation manquant"
    # Un volume nommé (persistant) et non un bind/tmpfs : le journal survit au redémarrage.
    journal = next(v for v in rem["volumes"] if ":/var/lib/remediation:" in v or v.endswith(":/var/lib/remediation"))
    vol_name = journal.split(":")[0]
    assert vol_name in COMPOSE.get("volumes", {}), f"{vol_name} doit être un volume nommé (persistance)"
    assert "/tmp" in (rem.get("tmpfs") or []), "tmpfs /tmp requis pour ansible-runner sous read_only"
