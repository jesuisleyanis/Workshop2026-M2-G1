#!/usr/bin/env python3
"""Banc de mesure de la latence de détection — attaque -> AnomalyEvent -> 1re action.

Mesure ce que le dashboard ne peut pas mesurer : le temps entre le DÉBUT d'une attaque et
(1) l'émission de l'AnomalyEvent par le detector (`event=anomaly_detected`),
(2) la première action du moteur de remédiation (`event=remediation_action`).
C'est la preuve chiffrée de la vitesse de détection (docs/plan-amelioration-detection.md, lot 0).

Pour chaque scénario x N passages : vide la deny-list du WAF, lance `attacks/run.sh`, lit les logs
JSON des conteneurs detector et remediation (contrat docs/contracts.md §1) jusqu'au premier
événement postérieur au départ, puis attend le cooldown avant le passage suivant.
Les horodatages des logs viennent de l'horloge de la VM Docker : le décalage avec l'hôte est
mesuré à chaque passage et corrigé.

Usage (stack levée, `make seed` fait) :
    python scripts/bench_detection.py                       # 3 scénarios x 3 passages
    python scripts/bench_detection.py --runs 5 --scenarios service_flood auth_abuse
    python scripts/bench_detection.py --quiet 600           # + 10 min sans attaque : faux positifs
Sortie : tableau p50/p95/max par scénario + JSON (--out). Code retour 0 si tout a été détecté.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS = ["service_flood", "auth_abuse", "web_attack"]
DETECTOR = "resilience-g1-detector-1"
REMEDIATION = "resilience-g1-remediation-1"
WAF = "resilience-g1-waf-1"


# ---------------------------------------------------------------- fonctions pures (testées)
def parse_ts(value: str) -> float:
    """Horodatage ISO 8601 du contrat de logs (`...Z`) -> epoch secondes."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def first_event(lines: list[str], event: str, since: float) -> tuple[float, dict] | None:
    """Premier log JSON `event` horodaté à `since` ou après (lignes non JSON ignorées)."""
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
            ts = parse_ts(entry["ts"])
        except (ValueError, KeyError, TypeError):
            continue
        if entry.get("event") == event and ts >= since:
            return ts, entry
    return None


def percentile(values: list[float], q: float) -> float:
    """Percentile par interpolation linéaire (q dans [0, 100])."""
    if not values:
        return math.nan
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    low, high = math.floor(pos), math.ceil(pos)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


@dataclass
class Run:
    scenario: str
    detection_s: float | None  # attaque -> AnomalyEvent
    action_s: float | None  # attaque -> 1re action de remédiation
    incident_type: str | None = None


@dataclass
class Summary:
    scenario: str
    runs: int
    detected: int
    p50_s: float
    p95_s: float
    max_s: float
    action_p50_s: float
    misrouted: list[str] = field(default_factory=list)


def summarize(runs: list[Run]) -> list[Summary]:
    out = []
    for scenario in dict.fromkeys(r.scenario for r in runs):
        rs = [r for r in runs if r.scenario == scenario]
        det = [r.detection_s for r in rs if r.detection_s is not None]
        act = [r.action_s for r in rs if r.action_s is not None]
        out.append(
            Summary(
                scenario=scenario,
                runs=len(rs),
                detected=len(det),
                p50_s=round(percentile(det, 50), 2),
                p95_s=round(percentile(det, 95), 2),
                max_s=round(max(det), 2) if det else math.nan,
                action_p50_s=round(percentile(act, 50), 2),
                misrouted=[
                    r.incident_type for r in rs if r.incident_type and r.incident_type != scenario
                ],
            )
        )
    return out


def incident_type_of(entry: dict) -> str | None:
    """Type d'incident d'un log `anomaly_detected` (« Anomalie <type> (score ...) »)."""
    words = str(entry.get("message", "")).split()
    return words[1] if len(words) > 1 and words[0] == "Anomalie" else None


# ---------------------------------------------------------------- effets de bord (Docker)
def docker_logs(container: str, since_epoch: float) -> list[str]:
    res = subprocess.run(
        ["docker", "logs", "--since", f"{since_epoch - 2:.3f}", container],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (res.stdout + res.stderr).splitlines()


def clock_offset(container: str) -> float:
    """Horloge VM Docker - horloge hôte (s), corrigée de la moitié de l'aller-retour."""
    t1 = time.time()
    res = subprocess.run(
        ["docker", "exec", container, "python", "-c", "import time;print(time.time())"],
        capture_output=True,
        text=True,
        check=True,
    )
    t2 = time.time()
    return float(res.stdout.strip()) - (t1 + t2) / 2


def clear_deny_list() -> None:
    subprocess.run(
        [
            "docker",
            "exec",
            WAF,
            "sh",
            "-c",
            'printf "# vidé par bench_detection\\n" > /etc/nginx/deny/blocked_ips.conf && nginx -s reload',
        ],
        capture_output=True,
        check=False,
    )


def run_once(scenario: str, args: argparse.Namespace) -> Run:
    clear_deny_list()
    offset = clock_offset(DETECTOR)
    t0 = time.time() + offset  # départ de l'attaque, dans l'horloge des logs
    attack = subprocess.Popen(
        [
            # bash du PATH (Git Bash sous Windows), pas celui que CreateProcess trouverait d'abord
            # dans System32 (WSL) ; chemin relatif à ROOT : run.sh déduit ROOT de son propre chemin.
            shutil.which("bash") or "bash",
            "attacks/run.sh",
            scenario,
            "--target",
            args.target,
            "--duration",
            str(args.duration),
            "--rate",
            str(args.rate),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    detection = action = None
    deadline = time.time() + args.duration + args.timeout
    while time.time() < deadline and (detection is None or action is None):
        time.sleep(0.5)
        if detection is None:
            detection = first_event(docker_logs(DETECTOR, t0), "anomaly_detected", t0)
        if action is None:
            action = first_event(docker_logs(REMEDIATION, t0), "remediation_action", t0)
    attack.wait()
    return Run(
        scenario=scenario,
        detection_s=round(detection[0] - t0, 2) if detection else None,
        action_s=round(action[0] - t0, 2) if action else None,
        incident_type=incident_type_of(detection[1]) if detection else None,
    )


def count_false_positives(seconds: float) -> int:
    t0 = time.time() + clock_offset(DETECTOR)
    time.sleep(seconds)
    return sum(1 for line in docker_logs(DETECTOR, t0) if '"anomaly_detected"' in line)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--scenarios", nargs="+", default=DEFAULT_SCENARIOS)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--target", default="https://localhost")
    p.add_argument("--duration", type=int, default=20, help="durée de chaque attaque (s, max 60)")
    p.add_argument("--rate", type=int, default=50)
    p.add_argument(
        "--timeout", type=float, default=60, help="attente max après la fin de l'attaque (s)"
    )
    p.add_argument(
        "--pause", type=float, default=75, help="pause entre passages (> cooldowns de 60 s)"
    )
    p.add_argument(
        "--quiet", type=float, default=0, help="secondes d'observation sans attaque (faux positifs)"
    )
    p.add_argument("--out", type=Path, default=ROOT / "bench-detection.json")
    args = p.parse_args(argv)

    fp = None
    if args.quiet:
        print(f"== observation sans attaque : {args.quiet:.0f} s ==")
        fp = count_false_positives(args.quiet)
    runs: list[Run] = []
    for scenario in args.scenarios:
        for i in range(1, args.runs + 1):
            print(f"== {scenario} {i}/{args.runs} ==", flush=True)
            run = run_once(scenario, args)
            print(
                f"   détection {run.detection_s} s · 1re action {run.action_s} s · type {run.incident_type}"
            )
            runs.append(run)
            time.sleep(args.pause)
    clear_deny_list()

    summary = summarize(runs)
    print(
        f"\n{'scénario':<16}{'détectés':>10}{'p50 (s)':>10}{'p95 (s)':>10}{'max (s)':>10}{'action p50':>12}"
    )
    for s in summary:
        print(
            f"{s.scenario:<16}{f'{s.detected}/{s.runs}':>10}{s.p50_s:>10}{s.p95_s:>10}{s.max_s:>10}{s.action_p50_s:>12}"
        )
    if fp is not None:
        print(f"faux positifs sur {args.quiet:.0f} s sans attaque : {fp}")
    args.out.write_text(
        json.dumps(
            {
                "runs": [asdict(r) for r in runs],
                "summary": [asdict(s) for s in summary],
                "false_positives": fp,
                "quiet_s": args.quiet,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"résultats -> {args.out}")
    return 0 if all(s.detected == s.runs for s in summary) else 1


if __name__ == "__main__":
    sys.exit(main())
