"""Capture Prometheus -> CSV avec un Prometheus simulé (httpx.MockTransport, query_range)."""

import csv
import io
from datetime import UTC, datetime

import httpx
import pytest

from ml.collector.capture import capture, main, parse_duration, parse_time, query_range
from ml.collector.collector import CollectError, build_queries
from ml.shared.csvio import CSV_COLUMNS
from ml.shared.features import FEATURE_NAMES

QUERIES = build_queries("20s")
BY_QUERY = {q: n for n, q in QUERIES.items()}
START = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
END = datetime(2026, 10, 19, 10, 1, tzinfo=UTC)
T = [START.timestamp() + 15 * i for i in range(5)]  # 10:00:00 .. 10:01:00


def make_transport(series: dict, seen: list | None = None, status="success"):
    """series : {feature: [(ts, "valeur"), ...]} ; feature absente = résultat vide."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/query_range"
        if seen is not None:
            seen.append(dict(request.url.params))
        if status != "success":
            return httpx.Response(200, json={"status": status, "error": "boom"})
        values = series.get(BY_QUERY[request.url.params["query"]])
        result = [] if values is None else [{"metric": {}, "values": [[t, v] for t, v in values]}]
        return httpx.Response(200, json={"status": "success",
                                         "data": {"resultType": "matrix", "result": result}})

    return httpx.MockTransport(handler)


def full_series(value="1.5"):
    return {n: [(t, value) for t in T] for n in FEATURE_NAMES}


def client(transport):
    return httpx.Client(base_url="http://prometheus:9090", transport=transport)


def test_capture_replays_collector_queries_on_the_same_grid():
    seen = []
    with client(make_transport(full_series(), seen)) as c:
        rows = capture(c, QUERIES, START, END, 15, "normal")
    assert len(rows) == 5
    assert rows[0][0] == "2026-10-19T10:00:00Z" and rows[-1][0] == "2026-10-19T10:01:00Z"
    assert all(r[1] == [1.5] * 9 and r[2] == "normal" and r[3] == () for r in rows)
    assert {p["query"] for p in seen} == set(QUERIES.values())  # mêmes requêtes que le collector
    assert all(p["step"] == "15" and float(p["start"]) == START.timestamp() for p in seen)


def test_missing_and_nan_become_zero_and_all_missing_rows_are_dropped():
    series = full_series()
    series.pop("db_errors_per_s")  # jamais d'erreur DB -> série absente
    series["ratio_4xx"] = [(T[0], "NaN")] + [(t, "0.02") for t in T[1:]]
    for n in FEATURE_NAMES:  # dernière fenêtre : plus rien du tout
        if n in series:
            series[n] = [(t, v) for t, v in series[n] if t != T[-1]]
    with client(make_transport(series)) as c:
        rows = capture(c, QUERIES, START, END, 15, "service_flood")
    assert len(rows) == 4
    i_db, i_4xx = FEATURE_NAMES.index("db_errors_per_s"), FEATURE_NAMES.index("ratio_4xx")
    assert rows[0][1][i_db] == 0.0 and rows[0][1][i_4xx] == 0.0
    assert set(rows[0][3]) == {"db_errors_per_s", "ratio_4xx"}
    assert rows[1][3] == ("db_errors_per_s",) and rows[1][1][i_4xx] == 0.02


def test_prometheus_error_raises_collect_error():
    with client(make_transport({}, status="error")) as c, pytest.raises(CollectError):
        query_range(c, "up", START, END, 15)


def test_main_writes_csv_file(tmp_path):
    out = tmp_path / "attacks.csv"
    args = ["--start", "2026-10-19T10:00:00Z", "--end", "2026-10-19T10:01:00Z",
            "--window", "20s", "--step", "15", "--label", "auth_abuse", "--out", str(out)]
    assert main(args, transport=make_transport(full_series())) == 0
    assert main(args + ["--no-header"], transport=make_transport(full_series())) == 0  # ajout
    with out.open(encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == list(CSV_COLUMNS)
    assert len(rows) == 1 + 10 and {r[-2] for r in rows[1:]} == {"auth_abuse"}


def test_main_to_stdout_and_exit_codes(capsys):
    w = ["--window", "20s"]
    assert main(["--last", "1m", "--end", "2026-10-19T10:01:00Z", *w],
                transport=make_transport(full_series())) == 0
    reader = csv.reader(io.StringIO(capsys.readouterr().out))
    assert next(reader) == list(CSV_COLUMNS)
    assert main(["--last", "1m", *w], transport=make_transport({})) == 1  # aucune donnée
    assert main(["--last", "1m", *w], transport=make_transport({}, status="error")) == 1


def test_parsers():
    assert parse_duration("90s").total_seconds() == 90
    assert parse_duration("2h").total_seconds() == 7200
    with pytest.raises(ValueError):
        parse_duration("10 minutes")
    assert parse_time("2026-10-19T10:00:00Z") == START
    assert parse_time("2026-10-19T10:00:00") == START  # naïf = UTC
