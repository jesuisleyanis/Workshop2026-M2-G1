"""Tests du banc de latence de détection (fonctions pures : aucun Docker)."""

import json
import math

import bench_detection as bench

T0 = bench.parse_ts("2026-10-21T10:00:00.000Z")


def log(event: str, ts: str, **extra) -> str:
    return json.dumps(
        {"ts": ts, "level": "WARNING", "service": "detector", "event": event, **extra}
    )


def test_parse_ts_reads_the_contract_format_in_utc() -> None:
    assert bench.parse_ts("2026-10-21T10:00:01.500Z") - T0 == 1.5


def test_first_event_ignores_older_events_other_events_and_non_json() -> None:
    lines = [
        'INFO:     172.21.0.5:36146 - "GET /metrics HTTP/1.1" 200 OK',
        log("anomaly_detected", "2026-10-21T09:59:59.000Z"),  # passage précédent
        log("log", "2026-10-21T10:00:01.000Z"),
        "{not json",
        log(
            "anomaly_detected",
            "2026-10-21T10:00:03.250Z",
            message="Anomalie service_flood (score 0.8)",
        ),
        log("anomaly_detected", "2026-10-21T10:00:09.000Z"),
    ]
    ts, entry = bench.first_event(lines, "anomaly_detected", T0)
    assert ts - T0 == 3.25
    assert bench.incident_type_of(entry) == "service_flood"


def test_first_event_returns_none_when_nothing_after_start() -> None:
    assert (
        bench.first_event(
            [log("anomaly_detected", "2026-10-21T09:00:00.000Z")], "anomaly_detected", T0
        )
        is None
    )


def test_percentile_interpolates_and_handles_empty() -> None:
    assert bench.percentile([1, 2, 3, 4, 5], 50) == 3
    assert bench.percentile([1, 2, 3, 4, 5], 95) == 4.8
    assert math.isnan(bench.percentile([], 95))


def test_summarize_counts_misses_and_misrouting() -> None:
    runs = [
        bench.Run("service_flood", 3.0, 3.2, "service_flood"),
        bench.Run("service_flood", 5.0, 5.1, "service_flood"),
        bench.Run("service_flood", None, None),
        bench.Run("auth_abuse", 2.0, 2.4, "service_flood"),
    ]
    flood, auth = bench.summarize(runs)
    assert (flood.runs, flood.detected, flood.p50_s, flood.max_s) == (3, 2, 4.0, 5.0)
    assert auth.misrouted == ["service_flood"]
