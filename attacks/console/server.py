"""Console Red Team — backend FastAPI local du banc d'essai de résilience.

Enveloppe `attacks/run.sh` / `reset.sh` / `scripts/verify_tx` derrière une petite API
locale et une UI. Les GARDE-FOUS sont appliqués CÔTÉ SERVEUR (plafonds rate/durée,
liste blanche des scénarios, cible validée) : l'UI ne peut pas les contourner.

Sécurité : à lancer UNIQUEMENT sur le PC Attaquant, en local (127.0.0.1). Ne JAMAIS
exposer ce service sur le réseau — il déclenche des générateurs d'attaque.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = ROOT / "attacks" / "scenarios"
RUNLOG = ROOT / "attacks" / ".runlog"
RUN_SH = ROOT / "attacks" / "run.sh"
CAMPAIGN_SH = ROOT / "attacks" / "campaign.sh"
RESET_SH = ROOT / "attacks" / "reset.sh"
VERIFY = ROOT / "scripts" / "verify_tx"
STATIC = Path(__file__).resolve().parent / "static"

# Plafonds de sécurité — identiques à run.sh, non franchissables depuis l'UI.
MAX_DURATION = 60
MAX_RATE = 100
DEFAULT_TARGET = os.environ.get("RESILIENCE_TARGET", "https://192.168.137.1")
# Périmètre offensif du projet (CLAUDE.md : « pas d'action offensive hors du réseau du projet »).
# Seuls ces hôtes sont des cibles valides ; surchargeable par ATTACK_ALLOWED_HOSTS (séparateur
# espace/virgule) pour un autre banc d'essai INTERNE. Toute autre cible -> 422 (fail closed).
_DEFAULT_ALLOWED_HOSTS = "192.168.137.1 127.0.0.1 localhost waf"
ALLOWED_HOSTS = {
    h for h in re.split(r"[\s,]+", os.environ.get("ATTACK_ALLOWED_HOSTS", _DEFAULT_ALLOWED_HOSTS))
    if h
}
# Scénarios lançables depuis la console (data_corruption est opérateur-only : exclu).
LAUNCHABLE = {"service_flood", "auth_abuse", "web_attack"}
DRY = os.environ.get("RESILIENCE_CONSOLE_DRY") == "1"

# Techniques avancées (hors scénarios-contrat) : chacune éprouve une facette de la défense.
# duration/rate = défauts raisonnables (re-plafonnés par run.sh).
TECHNIQUES = [
    {"name": "rotation", "label": "Rotation de source",
     "tests": "La remédiation par blocage d'IP tient-elle quand la source change ?",
     "duration": 25, "rate": 60},
    {"name": "pulse", "label": "Rafales pulsées",
     "tests": "Les seuils SOC en rate[1m] captent-ils des pics intermittents ?",
     "duration": 40, "rate": 70},
    {"name": "recon", "label": "Reconnaissance",
     "tests": "Le SOC voit-il l'énumération d'endpoints (angle mort recon → unknown) ?",
     "duration": 20, "rate": 10},
    {"name": "replay", "label": "Rejeu de transaction",
     "tests": "L'API déduplique-t-elle une transaction rejouée (intégrité) ?",
     "duration": 15, "rate": 20},
    {"name": "slow", "label": "Connexions lentes (Slowloris borné)",
     "tests": "Les timeouts / le pool de connexions résistent-ils à la lenteur ?",
     "duration": 30, "rate": 40},
]
TECHNIQUE_NAMES = {t["name"] for t in TECHNIQUES}

# --- Liaison Bleu (optionnelle) : API interne du moteur de remédiation. ----------
# NON joignable depuis le PC Attaquant (réseau interne) : ne renseigner ces variables
# QUE là où le moteur est accessible (PC Hôte, ou conteneur sur le réseau `app`).
# Le token reste CÔTÉ SERVEUR — jamais transmis au navigateur.
BLUE_BASE = os.environ.get("REMEDIATION_BASE")      # ex. http://remediation:8005
BLUE_TOKEN = os.environ.get("REMEDIATION_TOKEN")


def blue_configured() -> bool:
    return bool(BLUE_BASE and BLUE_TOKEN)


def _blue_get(path: str) -> Any:
    import json
    import ssl
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        BLUE_BASE.rstrip("/") + path,
        headers={"Authorization": f"Bearer {BLUE_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
        return json.loads(r.read())

_TARGET_RE = re.compile(r"^https?://[A-Za-z0-9._:\-\[\]]+/?$")


def clamp_params(duration: int, rate: int) -> tuple[int, int]:
    """Borne durée et débit aux plafonds de sécurité (jamais au-dessus, jamais < 1)."""
    return (
        max(1, min(int(duration), MAX_DURATION)),
        max(1, min(int(rate), MAX_RATE)),
    )


def validate_target(target: str) -> str:
    target = (target or "").strip() or DEFAULT_TARGET
    if not _TARGET_RE.match(target):
        raise HTTPException(422, f"Cible invalide : {target!r} (URL http(s) attendue)")
    host = urlsplit(target).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise HTTPException(
            422,
            f"Cible hors périmètre projet : {host!r} "
            f"(autorisés : {', '.join(sorted(ALLOWED_HOSTS))} ; cf. ATTACK_ALLOWED_HOSTS)",
        )
    return target.rstrip("/")


def load_scenarios() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in sorted(SCENARIO_DIR.glob("*.yml")):
        s = yaml.safe_load(f.read_text(encoding="utf-8"))
        out.append(
            {
                "name": s["name"],
                "objectif": " ".join(str(s.get("objectif", "")).split()),
                "cible": s.get("cible", {}),
                "incident_type": s.get("incident_type"),
                "signal": s.get("signal_attendu", {}),
                "remediation": s.get("remediation_attendue", []),
                "launchable": s["name"] in LAUNCHABLE,
            }
        )
    return out


class Runner:
    """Un seul scénario actif à la fois ; suit l'état pour l'UI."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.scenario: str | None = None
        self.target: str | None = None
        self.started_at: float | None = None
        self.duration: int | None = None
        self.last_argv: list[str] | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def launch(self, scenario: str, target: str, duration: int, rate: int) -> None:
        if scenario not in LAUNCHABLE:
            raise HTTPException(422, f"Scénario non lançable depuis la console : {scenario}")
        if self.running:
            raise HTTPException(409, f"Un scénario tourne déjà : {self.scenario}")
        argv = ["bash", str(RUN_SH), scenario,
                "--target", target, "--duration", str(duration), "--rate", str(rate)]
        self.last_argv = argv
        self.scenario, self.target, self.duration = scenario, target, duration
        self.started_at = time.time()
        if not DRY:
            self.proc = subprocess.Popen(argv, cwd=str(ROOT))

    def launch_technique(self, name: str, target: str, duration: int, rate: int) -> None:
        if name not in TECHNIQUE_NAMES:
            raise HTTPException(422, f"Technique inconnue : {name}")
        if self.running:
            raise HTTPException(409, f"Un scénario tourne déjà : {self.scenario}")
        argv = ["bash", str(RUN_SH), name,
                "--target", target, "--duration", str(duration), "--rate", str(rate)]
        self.last_argv = argv
        self.scenario, self.target, self.duration = name, target, duration
        self.started_at = time.time()
        if not DRY:
            self.proc = subprocess.Popen(argv, cwd=str(ROOT))

    def launch_campaign(self, target: str) -> None:
        if self.running:
            raise HTTPException(409, f"Un scénario tourne déjà : {self.scenario}")
        argv = ["bash", str(CAMPAIGN_SH), "--target", target]
        self.last_argv = argv
        self.scenario, self.target, self.duration = "campaign", target, None
        self.started_at = time.time()
        if not DRY:
            self.proc = subprocess.Popen(argv, cwd=str(ROOT))

    def stop(self) -> None:
        if not DRY:
            subprocess.run(["bash", str(RUN_SH), "--stop"], cwd=str(ROOT), timeout=15)
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None

    def status(self) -> dict[str, Any]:
        elapsed = time.time() - self.started_at if self.started_at else 0.0
        remaining = max(0.0, (self.duration or 0) - elapsed) if self.running else 0.0
        return {
            "running": self.running,
            "scenario": self.scenario if self.running else None,
            "target": self.target if self.running else None,
            "elapsed_s": round(elapsed, 1) if self.running else 0.0,
            "remaining_s": round(remaining, 1),
            "duration_s": self.duration if self.running else None,
            "dry_run": DRY,
        }


runner = Runner()


class RunRequest(BaseModel):
    scenario: str
    target: str = DEFAULT_TARGET
    duration: int = 20
    rate: int = 40


def create_app() -> FastAPI:
    app = FastAPI(title="Console Red Team — RESILIENCE-ALPHA", docs_url=None, redoc_url=None)

    @app.get("/api/scenarios")
    def scenarios() -> dict[str, Any]:
        return {"scenarios": load_scenarios(), "default_target": DEFAULT_TARGET,
                "max_duration": MAX_DURATION, "max_rate": MAX_RATE}

    @app.post("/api/run")
    def run(req: RunRequest) -> dict[str, Any]:
        target = validate_target(req.target)
        duration, rate = clamp_params(req.duration, req.rate)
        runner.launch(req.scenario, target, duration, rate)
        return {**runner.status(), "launched": req.scenario, "target": target,
                "duration": duration, "rate": rate}

    @app.get("/api/techniques")
    def techniques() -> dict[str, Any]:
        return {"techniques": TECHNIQUES}

    @app.post("/api/technique")
    def technique(req: RunRequest) -> dict[str, Any]:
        target = validate_target(req.target)
        meta = next((t for t in TECHNIQUES if t["name"] == req.scenario), None)
        if meta is None:
            raise HTTPException(422, f"Technique inconnue : {req.scenario}")
        duration, rate = clamp_params(meta["duration"], meta["rate"])
        runner.launch_technique(req.scenario, target, duration, rate)
        return {**runner.status(), "launched": req.scenario, "target": target,
                "duration": duration, "rate": rate}

    @app.post("/api/campaign")
    def campaign(req: RunRequest) -> dict[str, Any]:
        """Opération Triade : campagne multi-étapes corrélée (auth -> web -> flood)."""
        target = validate_target(req.target)
        runner.launch_campaign(target)
        return {**runner.status(), "launched": "campaign", "target": target}

    @app.post("/api/stop")
    def stop() -> dict[str, Any]:
        runner.stop()
        return {"stopped": True, **runner.status()}

    @app.post("/api/reset")
    def reset() -> dict[str, Any]:
        if not DRY:
            subprocess.run(["bash", str(RESET_SH)], cwd=str(ROOT), timeout=120)
        return {"reset": True}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return {**runner.status(), "blue": blue_configured()}

    @app.get("/api/blue/incidents")
    def blue_incidents() -> dict[str, Any]:
        """Relais lecture seule des incidents du moteur (détection/remédiation réelles)."""
        if not blue_configured():
            raise HTTPException(503, "Liaison Bleu non configurée (REMEDIATION_BASE/REMEDIATION_TOKEN).")
        try:
            data = _blue_get("/incidents?limit=20")
        except Exception as e:  # moteur injoignable (réseau interne, service down…)
            raise HTTPException(502, f"Moteur de remédiation injoignable : {e}")
        return {"connected": True, "incidents": data.get("incidents", [])}

    @app.get("/api/verify")
    def verify() -> dict[str, Any]:
        if DRY:
            return {"ok": True, "returncode": 0, "dry_run": True}
        rc = subprocess.run(["python3", str(VERIFY)], cwd=str(ROOT),
                            env={**os.environ, "BASE_URL": runner.target or DEFAULT_TARGET},
                            timeout=30).returncode
        return {"ok": rc == 0, "returncode": rc}

    @app.get("/api/stream")
    async def stream() -> StreamingResponse:
        async def gen():
            pos = RUNLOG.stat().st_size if RUNLOG.exists() else 0
            while True:
                if RUNLOG.exists():
                    size = RUNLOG.stat().st_size
                    if size > pos:
                        with RUNLOG.open("r", encoding="utf-8", errors="replace") as fh:
                            fh.seek(pos)
                            for line in fh:
                                line = line.rstrip("\n")
                                if line:
                                    yield f"event: log\ndata: {line}\n\n"
                        pos = size
                    elif size < pos:  # fichier tronqué (reset)
                        pos = 0
                st = runner.status()
                yield "event: status\ndata: " + _json(st) + "\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(STATIC / "index.html"))

    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    return app


def _json(d: dict[str, Any]) -> str:
    import json
    return json.dumps(d, ensure_ascii=False)


app = create_app()


if __name__ == "__main__":
    import uvicorn
    # Local-only : ne JAMAIS binder 0.0.0.0 (ce service déclenche des attaques).
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("CONSOLE_PORT", "8088")))
