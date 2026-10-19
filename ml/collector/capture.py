"""Capture de séries réelles Prometheus -> CSV de fenêtres de features.

Rejoue sur une PÉRIODE PASSÉE (`/api/v1/query_range`) exactement les requêtes du
collector temps réel (`build_queries`, même fenêtre `rate()`) : les fenêtres capturées
ont donc la même définition que celles que le detector score en démo.

Prometheus n'étant joignable que sur le réseau `obs`, on la lance DANS le conteneur
collector et on récupère le CSV sur stdout :

    docker compose exec -T collector python -m ml.collector.capture \\
        --last 30m --label normal > ml/training/data/baseline_real.csv
    docker compose exec -T collector python -m ml.collector.capture \\
        --start 2026-10-19T10:00:00Z --end 2026-10-19T10:03:00Z \\
        --label service_flood --no-header >> ml/training/data/attacks_real.csv

Mêmes règles que le collector pour les trous : feature absente/NaN -> 0.0 et listée
dans `missing` ; fenêtre où TOUT manque -> ignorée (jamais un vecteur de zéros).
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import httpx

from ml.collector.collector import CollectError, build_queries
from ml.shared.csvio import Row, write_rows
from ml.shared.features import FEATURE_NAMES

_DURATION = re.compile(r"^(\d+)([smh])$")
_UNIT_S = {"s": 1, "m": 60, "h": 3600}


def parse_duration(text: str) -> timedelta:
    """'90s', '30m', '2h' -> timedelta."""
    m = _DURATION.match(text.strip())
    if not m:
        raise ValueError(f"durée invalide {text!r} (ex. 90s, 30m, 2h)")
    return timedelta(seconds=int(m.group(1)) * _UNIT_S[m.group(2)])


def parse_time(text: str) -> datetime:
    """ISO 8601 ('2026-10-19T10:00:00Z') -> datetime UTC."""
    t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def query_range(client: httpx.Client, promql: str, start: datetime, end: datetime,
                step_s: float) -> dict[float, float]:
    """{timestamp: valeur} d'une requête sur [start, end] ; NaN/Inf ignorés."""
    try:
        resp = client.get("/api/v1/query_range", params={
            "query": promql, "start": start.timestamp(), "end": end.timestamp(), "step": step_s,
        })
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CollectError(f"Prometheus injoignable ou réponse invalide: {exc}") from exc
    if body.get("status") != "success":
        raise CollectError(f"Prometheus status={body.get('status')!r}: {body.get('error')}")
    result = body.get("data", {}).get("result", [])
    if not result:
        return {}
    out: dict[float, float] = {}
    for ts, raw in result[0].get("values", []):
        value = float(raw)
        if math.isfinite(value):
            out[float(ts)] = value
    return out


def capture(client: httpx.Client, queries: dict[str, str], start: datetime, end: datetime,
            step_s: float, label: str) -> list[Row]:
    """Fenêtres [start, end] au pas `step_s`, alignées sur la grille de Prometheus."""
    series = {name: query_range(client, queries[name], start, end, step_s) for name in FEATURE_NAMES}
    rows: list[Row] = []
    for ts in sorted(set().union(*series.values())):
        missing = tuple(n for n in FEATURE_NAMES if ts not in series[n])
        if len(missing) == len(FEATURE_NAMES):
            continue
        vector = [series[n].get(ts, 0.0) for n in FEATURE_NAMES]
        rows.append((_iso(ts), vector, label, missing))
    return rows


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    p = argparse.ArgumentParser(description="Capture des features réelles Prometheus en CSV")
    when = p.add_mutually_exclusive_group(required=True)
    when.add_argument("--last", help="durée jusqu'à maintenant (ex. 30m)")
    when.add_argument("--start", help="début ISO 8601 UTC (avec --end)")
    p.add_argument("--end", help="fin ISO 8601 UTC (défaut : maintenant)")
    p.add_argument("--label", default="normal", help="normal ou type de scénario")
    p.add_argument("--prometheus-url", default=os.getenv("PROMETHEUS_URL", "http://prometheus:9090"))
    p.add_argument("--window", default=os.getenv("PROM_RATE_WINDOW", "30s"),
                   help="fenêtre des rate() — DOIT être celle du collector en démo")
    p.add_argument("--step", type=float, default=float(os.getenv("COLLECT_INTERVAL_SECONDS", "15")),
                   help="pas en secondes — celui de la collecte temps réel")
    p.add_argument("--out", default="-", help="fichier CSV (défaut : stdout)")
    p.add_argument("--no-header", action="store_true", help="pour concaténer (>>) à un CSV existant")
    args = p.parse_args(argv)

    end = parse_time(args.end) if args.end else datetime.now(timezone.utc)
    start = end - parse_duration(args.last) if args.last else parse_time(args.start)
    if start >= end:
        p.error("début >= fin")

    with httpx.Client(base_url=args.prometheus_url.rstrip("/"), timeout=30.0,
                      transport=transport) as client:
        try:
            rows = capture(client, build_queries(args.window), start, end, args.step, args.label)
        except CollectError as exc:
            sys.stderr.write(f"capture: {exc}\n")
            return 1

    if args.out == "-":
        write_rows(sys.stdout, rows, header=not args.no_header)
    else:
        with open(args.out, "a" if args.no_header else "w", newline="", encoding="utf-8") as fh:
            write_rows(fh, rows, header=not args.no_header)
    incomplete = sum(1 for r in rows if r[3])
    sys.stderr.write(f"capture: {len(rows)} fenêtre(s) label={args.label} "
                     f"[{_iso(start.timestamp())} -> {_iso(end.timestamp())}] "
                     f"window={args.window} step={args.step:g}s, {incomplete} avec feature(s) manquante(s)\n")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
