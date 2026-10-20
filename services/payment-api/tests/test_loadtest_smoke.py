"""Fumée du harnais de charge : un mini-profil doit tourner sans erreur serveur.

On ne mesure pas une performance (variable selon la machine) ; on garantit que le
générateur construit la vraie app, forge des jetons valides, exerce les trois endpoints
et agrège correctement (débit, latences, portes SLO). C'est le filet anti-régression du
`loadtest/` lui-même, exécuté par `make test` comme n'importe quel test du composant.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import httpx
import pytest
from loadgen import (
    ACTIONS,
    _parse_weights,
    build_arg_parser,
    build_inprocess,
    format_report,
    main,
    result_to_dict,
    run_load,
)

DEFAULT_MIX = {"read_accounts": 4, "read_transactions": 3, "write_transaction": 3}


def _run_inprocess(**kwargs):
    async def _go():
        with tempfile.TemporaryDirectory(prefix="payapi-load-test-") as tmp:
            transport, users, engine = build_inprocess(
                kwargs.pop("users", 3),
                kwargs.pop("balance", 10_000_000),
                kwargs.get("concurrency", 4),
                Path(tmp) / "load.db",
            )
            try:
                return await run_load(transport=transport, users=users, **kwargs)
            finally:
                await transport.aclose()
                engine.dispose()

    return asyncio.run(_go())


def test_inprocess_load_runs_without_server_errors():
    result = _run_inprocess(concurrency=4, requests=120)

    assert result.total == 120
    assert result.errors == 0, f"statuts observés : {result.overall.statuses}"
    # seuls des statuts métier légitimes : 200 (lectures) et 201 (virement créé).
    assert set(result.overall.statuses) <= {200, 201}
    assert result.rps > 0
    # les trois endpoints du mélange par défaut ont bien été exercés.
    assert set(result.by_endpoint) == set(ACTIONS)


def test_percentiles_are_monotonic_and_report_renders():
    result = _run_inprocess(concurrency=4, requests=150)
    st = result.overall
    assert 0 <= st.p50 <= st.p95 <= st.p99 <= st.max

    report = format_report(result)
    assert "payment-api — test de charge" in report
    assert "TOTAL" in report

    payload = result_to_dict(result)
    assert payload["total"] == 150
    assert payload["overall"]["latency_ms"]["p95"] >= payload["overall"]["latency_ms"]["p50"]


def test_duration_mode_respects_wall_clock():
    result = _run_inprocess(concurrency=4, duration=1.0)
    assert result.total > 0
    assert result.wall_s == pytest.approx(1.0, abs=0.6)


def test_write_only_mix_creates_transactions():
    result = _run_inprocess(concurrency=2, requests=40, weights={"write_transaction": 1})
    assert set(result.by_endpoint) == {"write_transaction"}
    assert result.overall.statuses.get(201, 0) == 40


def test_run_load_requires_exactly_one_target():
    async def _go():
        with pytest.raises(ValueError):
            await run_load(users=[], concurrency=1, requests=1)

    asyncio.run(_go())


def test_run_load_rejects_zero_concurrency():
    # garde-fou : -c 0 ne doit pas planter sur divmod(n, 0) mais lever proprement.
    async def _go():
        with tempfile.TemporaryDirectory(prefix="payapi-load-test-") as tmp:
            transport, users, engine = build_inprocess(1, 1_000_000, 1, Path(tmp) / "load.db")
            try:
                with pytest.raises(ValueError):
                    await run_load(transport=transport, users=users, concurrency=0, requests=10)
            finally:
                await transport.aclose()
                engine.dispose()

    asyncio.run(_go())


def test_mix_spec_defines_whole_mix():
    # régression : --mix "write_transaction=1" doit être écriture seule, pas 4:3:1.
    assert _parse_weights("write_transaction=1", DEFAULT_MIX) == {
        "read_accounts": 0,
        "read_transactions": 0,
        "write_transaction": 1,
    }
    assert _parse_weights(None, DEFAULT_MIX) == DEFAULT_MIX


def test_cli_exposes_auth_url():
    args = build_arg_parser().parse_args(
        ["--url", "http://api:8001", "--auth-url", "http://auth:8002"]
    )
    assert args.url == "http://api:8001"
    assert args.auth_url == "http://auth:8002"


def test_cli_parses_mix_and_slo_gates():
    args = build_arg_parser().parse_args(
        ["-c", "8", "-n", "100", "--mix", "write_transaction=5", "--max-p95-ms", "500"]
    )
    assert args.concurrency == 8
    assert args.requests == 100
    assert args.max_p95_ms == 500


def test_main_slo_gate_breach_returns_code_2(capsys):
    # p95 forcément > 0.0001 ms → la porte SLO échoue, code de sortie 2.
    code = main(["-c", "4", "-n", "60", "--max-p95-ms", "0.0001"])
    assert code == 2
    assert "SLO non respectée" in capsys.readouterr().err


def test_asgi_transport_is_used_for_inprocess():
    # garde-fou : le mode in-process ne doit jamais ouvrir de socket réseau.
    with tempfile.TemporaryDirectory(prefix="payapi-load-test-") as tmp:
        transport, users, engine = build_inprocess(2, 1_000_000, 2, Path(tmp) / "load.db")
        try:
            assert isinstance(transport, httpx.ASGITransport)
            assert len(users) == 2
            assert all(u.src != u.dst for u in users)
        finally:
            asyncio.run(transport.aclose())
            engine.dispose()
