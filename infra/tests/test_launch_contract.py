"""Contrat de lancement de la stack (vérifiable sans Docker).

Verrouille les points qui ont cassé le lancement (docs/plan-optimisation-lancement.md) :
- C1 : le profil `ml` (collector + detector) doit être levé par `make up*` — sans lui, pas de détection ;
- C2 : Compose doit recevoir `--env-file .env` (sinon il cherche infra/compose/.env, absent) ;
- C3 : `.dockerignore` racine = contexte léger ET contrôle anti-fuite de secrets ;
- C5 : cache pip BuildKit dans les étapes de build ;
- C6 : démarrage ordonné sur l'état *healthy* des dépendances.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load(
    (ROOT / "infra" / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
)
SERVICES = COMPOSE["services"]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")


# ---------------------------------------------------------------- Makefile
def _make_var(name: str) -> str:
    """Valeur d'une variable du Makefile, variables $(X) imbriquées résolues."""
    match = re.search(rf"^{name}[ \t]*[:?]?=[ \t]*(.*)$", MAKEFILE, re.MULTILINE)
    assert match, f"variable {name} absente du Makefile"
    return re.sub(r"\$\((\w+)\)", lambda m: _make_var(m.group(1)), match.group(1))


def _target(name: str) -> tuple[list[str], str]:
    """(prérequis, recette) d'une cible du Makefile."""
    match = re.search(
        rf"^{re.escape(name)}:([^#\n]*)(?:##.*)?\n((?:\t.*\n)*)", MAKEFILE, re.MULTILINE
    )
    assert match, f"cible {name} absente du Makefile"
    return match.group(1).split(), match.group(2)


def _declared_profiles() -> set[str]:
    return {p for svc in SERVICES.values() for p in svc.get("profiles", [])}


def test_compose_receives_the_root_env_file() -> None:
    # C2 : Compose lit par défaut le .env du répertoire du fichier compose (infra/compose/).
    assert "--env-file .env" in _make_var("COMPOSE")


def test_every_launch_target_starts_the_ml_profile() -> None:
    # C1 : sans collector + detector, la démo n'a aucune détection (Zero-Touch impossible).
    assert "--profile ml" in _make_var("PROFILES_DEMO")
    for target in ("up", "up-full", "up-iot", "start", "start-full", "build"):
        _, recipe = _target(target)
        resolved = re.sub(
            r"\$\((\w+)\)",
            lambda m: _make_var(m.group(1)) if m.group(1) != "COMPOSE" else "",
            recipe,
        )
        assert "--profile ml" in resolved, f"make {target} ne lève pas le profil ml"


def test_down_and_ps_cover_every_declared_profile() -> None:
    # Un service d'un profil oublié survivrait à `make down` (ex. detector lancé à la main).
    profiles = _make_var("PROFILES_ALL")
    for profile in _declared_profiles():
        assert f"--profile {profile}" in profiles, f"PROFILES_ALL n'inclut pas le profil {profile}"
    for target in ("down", "ps"):
        assert "$(PROFILES_ALL)" in _target(target)[1], (
            f"make {target} doit couvrir tous les profils"
        )


def test_up_does_not_train_on_the_host() -> None:
    # C4 : le build du detector entraîne déjà le modèle (étape `trainer`) ; pas de sklearn requis sur le poste.
    for target in ("up", "up-full", "up-iot"):
        prereqs, _ = _target(target)
        assert "model" not in prereqs, f"make {target} ne doit plus dépendre de `model`"
        assert "check-env" in prereqs, f"make {target} doit échouer clairement sans .env"


def test_start_targets_do_not_rebuild() -> None:
    for target in ("start", "start-full"):
        assert "--build" not in _target(target)[1], f"make {target} doit relancer sans rebuild"


# ---------------------------------------------------------------- .dockerignore
DOCKERIGNORE = [
    line.strip()
    for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#")
]


def _ignored(path: str) -> bool:
    for pattern in DOCKERIGNORE:
        bare = pattern.removeprefix("**/")
        if (
            fnmatch.fnmatch(path, pattern)
            or fnmatch.fnmatch(path, bare)
            or path.startswith(pattern.rstrip("/") + "/")
        ):
            return True
        if pattern.startswith("**/") and any(
            fnmatch.fnmatch(part, bare) for part in path.split("/")
        ):
            return True
    return False


def _root_context_dockerfiles() -> list[Path]:
    files = []
    for svc in SERVICES.values():
        build = svc.get("build")
        if isinstance(build, dict) and build.get("context") == "../.." and "dockerfile" in build:
            files.append(ROOT / build["dockerfile"])
    return files


def test_dockerignore_blocks_secrets_and_heavy_dirs() -> None:
    for path in (
        ".env",
        ".git",
        ".venv",
        "security/sops/secrets.env",
        "x/age.key",
        "graphify-out",
        "a/node_modules",
    ):
        assert _ignored(path), f".dockerignore doit exclure {path}"


def test_dockerignore_keeps_every_build_input() -> None:
    # Ce que les Dockerfiles copient depuis la racine ne doit JAMAIS être exclu (build cassé sinon).
    dockerfiles = _root_context_dockerfiles()
    assert len(dockerfiles) >= 6
    for dockerfile in dockerfiles:
        for line in dockerfile.read_text(encoding="utf-8").splitlines():
            if not line.startswith("COPY") or "--from=" in line:
                continue
            sources = [tok for tok in line.split()[1:-1] if not tok.startswith("--")]
            for src in sources:
                assert not _ignored(src), (
                    f"{dockerfile.relative_to(ROOT)} copie {src}, exclu par .dockerignore"
                )
    # Données réelles + calibration embarquées par le build du detector.
    assert not _ignored("ml/training/data/baseline_real.csv")
    assert not _ignored("ml/training/data/calibration.json")


def test_build_stages_use_the_pip_cache_mount() -> None:
    for dockerfile in _root_context_dockerfiles():
        text = dockerfile.read_text(encoding="utf-8")
        name = dockerfile.relative_to(ROOT)
        assert "PIP_NO_CACHE_DIR" not in text, f"{name}: PIP_NO_CACHE_DIR annule le cache BuildKit"
        instructions = re.sub(
            r"\\\r?\n", " ", text
        ).splitlines()  # RUN multi-lignes -> une instruction
        for line in instructions:
            if line.startswith("RUN") and "pip install" in line:
                assert "--mount=type=cache,target=/root/.cache/pip" in line, (
                    f"{name}: pip sans cache BuildKit : {line}"
                )


# ---------------------------------------------------------------- démarrage ordonné
# Dépendances FACULTATIVES : la chaîne de paiement (WAF -> auth) ne doit jamais attendre le chargement
# du modèle de reconnaissance faciale (si face-id n'est pas prêt, auth répond 503 au seul back-office),
# ni le broker de la LED (`required: false`, LED fail-open, ADR 0006), ni le back-office (le WAF, donc
# tout le paiement, démarre même si le back-office est lent ou en échec : 502 sur :9443 seulement).
OPTIONAL_DEPS = {("auth", "face-id"), ("auth", "mosquitto"), ("waf", "backoffice")}


def test_dependencies_with_a_healthcheck_are_awaited_healthy() -> None:
    # C6 : attendre qu'une dépendance soit *healthy* (pas seulement démarrée) quand elle sait le dire.
    for name, svc in SERVICES.items():
        deps = svc.get("depends_on") or {}
        for dep in deps:
            if "healthcheck" not in SERVICES[dep] or (name, dep) in OPTIONAL_DEPS:
                continue
            assert isinstance(deps, dict), (
                f"{name}: depends_on en liste, condition de santé impossible"
            )
            assert deps[dep].get("condition") == "service_healthy", (
                f"{name} -> {dep} : service_healthy attendu"
            )


def test_waf_does_not_wait_for_a_healthy_backoffice() -> None:
    # Un back-office qui ne devient jamais healthy ne doit pas bloquer le démarrage du WAF (paiement).
    assert SERVICES["waf"]["depends_on"]["backoffice"]["condition"] == "service_started"


def test_local_ui_overlay_publishes_only_on_loopback():
    # make ui : le dashboard (vue d'ensemble du SI) n'est publié que sur 127.0.0.1, jamais sur le hotspot.
    overlay = yaml.safe_load(
        (ROOT / "infra" / "compose" / "docker-compose.ui-local.yml").read_text(encoding="utf-8")
    )["services"]
    assert set(overlay) == {"dashboard"}
    for port in overlay["dashboard"]["ports"]:
        assert str(port).startswith("127.0.0.1:"), port


def test_remediation_reaches_the_waf_on_its_container_port_and_protects_the_edge_gateway():
    rem = SERVICES["remediation"]["environment"]
    # Le WAF non-root écoute 8443 DANS le conteneur : https://waf (443) = verify_tx toujours KO.
    assert rem["BASE_URL"] == "https://waf:8443"
    # Sous Docker Desktop, tous les clients externes ont l'IP d'une passerelle d'un réseau du WAF :
    # chacune doit avoir un sous-réseau fixe ET être protégée (sinon bloquer = couper tout le monde).
    protected = rem["NEVER_BLOCK_IPS"].split(",")
    excluded = SERVICES["detector"]["environment"]["SOURCE_IP_EXCLUDE"].split(",")
    for net in SERVICES["waf"]["networks"]:
        subnet = COMPOSE["networks"][net]["ipam"]["config"][0]["subnet"]
        # réseau ENTIER : passerelle (tous les clients externes) ET services (verify_tx de la remédiation)
        assert subnet in protected, f"réseau {net} non protégé contre le blocage"
        assert subnet in excluded, f"réseau {net} candidat comme IP source"


def test_ansible_temp_dirs_are_writable_in_the_read_only_remediation_image():
    dockerfile = (ROOT / "remediation" / "Dockerfile").read_text(encoding="utf-8")
    for var in ("ANSIBLE_LOCAL_TEMP=/tmp/", "ANSIBLE_REMOTE_TMP=/tmp/"):
        assert var in dockerfile, var  # sinon « Failed to create temporary directory »


def test_only_the_remediation_fixed_ip_is_exempt_from_the_login_rate_limit():
    ip = SERVICES["remediation"]["networks"]["app"]["ipv4_address"]
    exempt = SERVICES["auth"]["environment"]["RATE_LIMIT_EXEMPT_IPS"].split(",")
    assert exempt == [ip]  # une IP exacte, jamais une plage (les clients externes = passerelle Docker)
    gateway = COMPOSE["networks"]["app"]["ipam"]["config"][0]["gateway"]
    assert ip != gateway


def test_services_trust_x_forwarded_for_only_from_the_waf_fixed_ip():
    # Sinon un conteneur du réseau app joint auth:8002 en direct avec `X-Forwarded-For: <IP exemptée>`
    # et brute-force /login sans limite.
    import ipaddress

    waf_ip = SERVICES["waf"]["networks"]["app"]["ipv4_address"]
    for svc in ("auth", "payment-api"):
        assert SERVICES[svc]["environment"]["TRUSTED_PROXIES"] == waf_ip, svc
    exempt = SERVICES["auth"]["environment"]["RATE_LIMIT_EXEMPT_IPS"]
    assert waf_ip != exempt
    # IP fixes hors de la plage d'allocation dynamique : jamais prises par un autre conteneur.
    dyn = ipaddress.ip_network(COMPOSE["networks"]["app"]["ipam"]["config"][0]["ip_range"])
    for ip in (waf_ip, SERVICES["remediation"]["networks"]["app"]["ipv4_address"]):
        assert ipaddress.ip_address(ip) not in dyn, ip


# ---------------------------------------------------------------- mode « IP réelle » (Caddy natif)
def test_by_default_the_waf_never_trusts_x_forwarded_for():
    # Sans proxy de confiance devant lui, croire X-Forwarded-For = un client choisit son IP
    # (échapper au blocage, faire bloquer quelqu'un d'autre, contourner la limitation de débit).
    assert SERVICES["waf"]["environment"]["WAF_TRUST_FORWARDED_FROM"] == ""


def test_real_ip_overlay_publishes_the_waf_on_loopback_and_trusts_only_docker_gateways():
    class ComposeLoader(yaml.SafeLoader):  # balise Compose `!override` (remplace la liste de base)
        pass

    ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))
    overlay = yaml.load(  # noqa: S506 — SafeLoader + une seule balise ajoutée
        (ROOT / "infra/compose/docker-compose.realip.yml").read_text(encoding="utf-8"), Loader=ComposeLoader
    )
    waf = overlay["services"]["waf"]
    # Seul Caddy (même poste) peut joindre le WAF : personne ne contourne le proxy depuis le hotspot.
    assert all(str(p).startswith("127.0.0.1:") for p in waf["ports"]), waf["ports"]
    trusted = waf["environment"]["WAF_TRUST_FORWARDED_FROM"].split(",")
    gateways = {COMPOSE["networks"][n]["ipam"]["config"][0]["gateway"] for n in SERVICES["waf"]["networks"]}
    assert set(trusted) == gateways  # ni plage, ni IP de client : uniquement le trafic publié en local


def test_caddy_overwrites_x_forwarded_for_and_targets_the_loopback_waf():
    caddy = (ROOT / "infra/caddy/Caddyfile").read_text(encoding="utf-8")
    overlay = (ROOT / "infra/compose/docker-compose.realip.yml").read_text(encoding="utf-8")
    assert "header_up X-Forwarded-For {remote_host}" in caddy  # écrase la valeur du client
    assert "reverse_proxy https://127.0.0.1:8443" in caddy and '"127.0.0.1:8443:8443"' in overlay
    assert "admin off" in caddy and "https://192.168.137.1" in caddy


def test_caddy_listens_only_on_the_hotspot_and_loopback_by_default():
    # Sans default_bind, Caddy écoute sur TOUTES les interfaces (le nom d'hôte ne filtre que `Host`).
    caddy = (ROOT / "infra/caddy/Caddyfile").read_text(encoding="utf-8")
    directives = "\n".join(line.split("#", 1)[0] for line in caddy.splitlines())
    match = re.search(r"^\s*default_bind \{\$CADDY_BIND:([^}]*)\}\s*$", directives, re.MULTILINE)
    assert match, "default_bind {$CADDY_BIND:...} absent du bloc global"
    assert match.group(1).split() == ["192.168.137.1", "127.0.0.1"]
    assert directives.index("default_bind") < directives.index("https://192.168.137.1")  # bloc global
    recipe = _target("caddy")[1]
    assert 'CADDY_BIND="$(CADDY_BIND)"' in recipe  # surcharge : make caddy CADDY_BIND=127.0.0.1


# ---------------------------------------------------------------- dépendances Python
def test_requirements_files_pin_each_package_once() -> None:
    # Un paquet listé deux fois finit tôt ou tard épinglé à deux versions différentes (pip échoue au build).
    for req in sorted(ROOT.glob("**/requirements*.txt")):
        if "node_modules" in req.parts:
            continue
        names: list[str] = []
        for line in req.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            names.append(re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].lower().replace("_", "-"))
        dups = {n for n in names if names.count(n) > 1}
        assert not dups, f"{req.relative_to(ROOT)} : doublons {sorted(dups)}"


# ---------------------------------------------------------------- make unblock
def test_make_unblock_empties_the_deny_file_the_waf_actually_reads() -> None:
    # La deny-list appartient à la remédiation (volume waf-deny) : écrite depuis SON conteneur, au chemin
    # lu par GET /waf/blocked-ips (WAF_DENY_FILE), puis WAF rechargé. Sinon `make unblock` ne débloque rien.
    recipe = re.search(r"^unblock:.*\n((?:\t.*\n)+)", MAKEFILE, re.MULTILINE)
    assert recipe, "cible make unblock absente"
    body = recipe.group(1)
    assert "exec -T remediation" in body and "/etc/resilience/waf-deny/blocked_ips.conf" in body
    assert "exec -T waf nginx -s reload" in body
    assert any(str(v).startswith("waf-deny:/etc/resilience/waf-deny:") for v in SERVICES["remediation"]["volumes"])
    config = (ROOT / "remediation" / "config.py").read_text(encoding="utf-8")
    assert '"/etc/resilience/waf-deny/blocked_ips.conf"' in config
