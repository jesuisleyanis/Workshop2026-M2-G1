"""Générateur de charge pour payment-api — latence, débit, taux d'erreur, portes SLO.

Deux cibles :

* **in-process** (défaut) : construit la *vraie* app FastAPI (`create_app`) sur une
  base SQLite fichier (WAL, multi-connexions) seedée, et la pilote via le transport
  ASGI de httpx. Aucun serveur, aucun Docker, aucun PostgreSQL — reproductible sur le
  poste de dev. Les jetons JWT sont forgés directement (même secret que l'app).
* **live** (`--url http://host:port`) : tape une instance réellement déployée en HTTP,
  s'authentifie via `POST /api/v1/login` et découvre les comptes via `GET /accounts`.
  Destiné à la recette sur la stack réelle (PostgreSQL, WAF).

Le profil est une **boucle fermée** : `--concurrency` utilisateurs virtuels bouclent sur
un mélange pondéré de lectures (comptes, historique) et d'écritures (virement d'1 cent
entre deux comptes du même utilisateur, jamais à court de solde). Charge pilotée par
durée (`--duration`) ou par volume (`--requests`).

Le harnais ne mesure pas la justesse métier (couverte par les tests pytest et le test
d'intégration PostgreSQL concurrent) : il mesure le *comportement sous charge* — ce que
le jury attend d'un démonstrateur de résilience (cf. docs/pca-pra.md : capacité, et
distinction avec le scénario `service_flood`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import secrets
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import QueuePool

# --------------------------------------------------------------------------- types


@dataclass(slots=True)
class Sample:
    """Une requête effectuée : endpoint logique, statut HTTP, latence (ms), succès."""

    endpoint: str
    status: int
    ms: float
    ok: bool


@dataclass
class EndpointStats:
    count: int
    errors: int
    rps: float
    p50: float
    p90: float
    p95: float
    p99: float
    max: float
    statuses: dict[int, int]

    @property
    def error_rate(self) -> float:
        return self.errors / self.count if self.count else 0.0


@dataclass
class LoadResult:
    target: str
    concurrency: int
    users: int
    wall_s: float
    total: int
    errors: int
    rps: float
    overall: EndpointStats
    by_endpoint: dict[str, EndpointStats]
    weights: dict[str, int]

    @property
    def error_rate(self) -> float:
        return self.errors / self.total if self.total else 0.0


@dataclass
class VirtualUser:
    """Un utilisateur seedé : jeton + deux comptes lui appartenant (src != dst)."""

    headers: dict[str, str]
    src: int
    dst: int


# ----------------------------------------------------------- forge de jetons / seed

TOKEN_TTL = timedelta(hours=1)


def make_token(sub: str, secret: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode({"sub": sub, "iat": now, "exp": now + TOKEN_TTL}, secret, algorithm="HS256")


def _sqlite_engine(path: Path, pool_size: int) -> Engine:
    """SQLite fichier en WAL : plusieurs connexions concurrentes, écritures sérialisées.

    (La base en mémoire partagée via StaticPool ne tolère pas l'accès concurrent : une
    seule connexion. Pour un test de charge il faut un vrai pool.)
    """
    engine = create_engine(
        f"sqlite+pysqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=QueuePool,
        pool_size=max(pool_size, 5),
        max_overflow=max(pool_size, 5),
        pool_timeout=30,
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def seed_inprocess(
    engine: Engine, n_users: int, balance_cents: int, secret: str
) -> list[VirtualUser]:
    """Crée demo01..demoNN, chacun avec deux comptes largement provisionnés.

    Le solde est volontairement énorme pour que les virements d'1 cent de la charge ne
    l'épuisent jamais — on mesure le débit, pas les règles de rejet pour solde.
    """
    from resilience_db import Account, Base, User, make_session_factory

    Base.metadata.create_all(engine)
    users: list[VirtualUser] = []
    with make_session_factory(engine)() as session:
        for n in range(1, n_users + 1):
            username = f"demo{n:02d}"
            user = User(username=username, password_hash="x")
            user.accounts += [
                Account(
                    iban_fake=f"FR76 LOAD {n:04d} A", balance_cents=balance_cents, currency="EUR"
                ),
                Account(
                    iban_fake=f"FR76 LOAD {n:04d} B", balance_cents=balance_cents, currency="EUR"
                ),
            ]
            session.add(user)
            session.flush()
            users.append(
                VirtualUser(
                    headers={"Authorization": f"Bearer {make_token(username, secret)}"},
                    src=user.accounts[0].id,
                    dst=user.accounts[1].id,
                )
            )
        session.commit()
    return users


def build_inprocess(
    n_users: int, balance_cents: int, pool_size: int, db_path: Path
) -> tuple[httpx.ASGITransport, list[VirtualUser], Engine]:
    """Construit (transport ASGI, utilisateurs virtuels, engine) sur SQLite fichier.

    L'engine est renvoyé pour que l'appelant le `dispose()` en fin de run (fermeture du
    pool de connexions, pas de fuite de descripteurs sur des runs répétés).
    """
    from payment_api.config import Settings
    from payment_api.main import create_app

    secret = secrets.token_hex(32)
    engine = _sqlite_engine(db_path, pool_size)
    users = seed_inprocess(engine, n_users, balance_cents, secret)
    # WARNING : on ne veut pas inonder le rapport des logs JSON transaction_created.
    app = create_app(Settings(jwt_secret=secret, run_migrations=False, log_level="WARNING"), engine)
    transport = httpx.ASGITransport(app=app)
    return transport, users, engine


async def discover_live_users(
    auth_url: str, api_url: str, n_users: int, password: str, timeout: float
) -> list[VirtualUser]:
    """Mode live : login réel (service `auth`) + découverte des comptes (service `payment-api`).

    `auth_url` et `api_url` sont distincts car `/login` est servi par `auth` tandis que
    `/accounts` et `/transactions` le sont par `payment-api` (deux services séparés).
    En déploiement derrière un ingress unique qui route les deux, passer la même URL.
    """
    auth_base = auth_url.rstrip("/")
    api_base = api_url.rstrip("/")
    users: list[VirtualUser] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for n in range(1, n_users + 1):
            username = f"demo{n:02d}"
            resp = await client.post(
                f"{auth_base}/api/v1/login", json={"username": username, "password": password}
            )
            resp.raise_for_status()
            headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
            acc = await client.get(f"{api_base}/api/v1/accounts", headers=headers)
            acc.raise_for_status()
            accounts = acc.json()
            if len(accounts) < 2:
                raise RuntimeError(
                    f"{username} possède {len(accounts)} compte(s) ; il en faut 2 pour un virement."
                )
            users.append(VirtualUser(headers=headers, src=accounts[0]["id"], dst=accounts[1]["id"]))
    return users


# --------------------------------------------------------------------- génération

ACTIONS = ("read_accounts", "read_transactions", "write_transaction")


def _weighted_actions(weights: dict[str, int]) -> list[str]:
    pool: list[str] = []
    for action in ACTIONS:
        pool += [action] * max(0, weights.get(action, 0))
    if not pool:
        raise ValueError("Au moins un poids d'action doit être > 0.")
    return pool


async def _do_action(client: httpx.AsyncClient, action: str, vu: VirtualUser) -> httpx.Response:
    if action == "read_accounts":
        return await client.get("/api/v1/accounts", headers=vu.headers)
    if action == "read_transactions":
        return await client.get("/api/v1/transactions?limit=50", headers=vu.headers)
    return await client.post(
        "/api/v1/transactions",
        headers=vu.headers,
        json={"src_account": vu.src, "dst_account": vu.dst, "amount_cents": 1},
    )


async def _worker(
    client: httpx.AsyncClient,
    users: list[VirtualUser],
    action_pool: list[str],
    rng: random.Random,
    samples: list[Sample],
    *,
    deadline: float | None,
    budget: int | None,
) -> None:
    """Un utilisateur virtuel : boucle fermée jusqu'à la deadline ou l'épuisement du budget."""
    taken = 0
    while True:
        if deadline is not None and time.perf_counter() >= deadline:
            return
        if budget is not None and taken >= budget:
            return
        taken += 1
        action = rng.choice(action_pool)
        vu = rng.choice(users)
        t0 = time.perf_counter()
        try:
            resp = await _do_action(client, action, vu)
            ms = (time.perf_counter() - t0) * 1000.0
            ok = resp.status_code < 500
            samples.append(Sample(action, resp.status_code, ms, ok))
        except Exception:  # noqa: BLE001 — toute erreur (transport/timeout) = échec dur, statut 0
            ms = (time.perf_counter() - t0) * 1000.0
            samples.append(Sample(action, 0, ms, False))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[k]


def _summarize(samples: list[Sample], wall_s: float) -> EndpointStats:
    latencies = [s.ms for s in samples]
    errors = sum(1 for s in samples if not s.ok)
    statuses = dict(Counter(s.status for s in samples))
    return EndpointStats(
        count=len(samples),
        errors=errors,
        rps=len(samples) / wall_s if wall_s > 0 else 0.0,
        p50=_percentile(latencies, 50),
        p90=_percentile(latencies, 90),
        p95=_percentile(latencies, 95),
        p99=_percentile(latencies, 99),
        max=max(latencies) if latencies else 0.0,
        statuses=statuses,
    )


async def run_load(
    *,
    transport: httpx.ASGITransport | None = None,
    base_url: str | None = None,
    users: list[VirtualUser],
    concurrency: int,
    duration: float | None = None,
    requests: int | None = None,
    weights: dict[str, int] | None = None,
    timeout: float = 30.0,
    seed: int = 1234,
) -> LoadResult:
    """Lance la charge et agrège le résultat. Fournir `transport` (ASGI) OU `base_url`."""
    if (transport is None) == (base_url is None):
        raise ValueError("Fournir exactement l'un de `transport` ou `base_url`.")
    if concurrency < 1:
        raise ValueError("concurrency doit être >= 1.")
    weights = weights or {"read_accounts": 4, "read_transactions": 3, "write_transaction": 3}
    action_pool = _weighted_actions(weights)
    samples: list[Sample] = []

    if requests is not None:
        # réparti équitablement entre les workers (le reste va aux premiers).
        base, extra = divmod(requests, concurrency)

    client_kwargs: dict = {"timeout": timeout}
    if transport is not None:
        client_kwargs["transport"] = transport
        client_kwargs["base_url"] = "http://loadtest.internal"
    else:
        client_kwargs["base_url"] = base_url

    async with httpx.AsyncClient(**client_kwargs) as client:
        t_start = time.perf_counter()
        deadline = t_start + duration if duration is not None else None
        tasks = []
        for i in range(concurrency):
            worker_budget = None
            if requests is not None:
                worker_budget = base + (1 if i < extra else 0)
            tasks.append(
                _worker(
                    client,
                    users,
                    action_pool,
                    random.Random(seed + i),
                    samples,
                    deadline=deadline,
                    budget=worker_budget,
                )
            )
        await asyncio.gather(*tasks)
        wall_s = time.perf_counter() - t_start

    overall = _summarize(samples, wall_s)
    by_endpoint = {
        action: _summarize([s for s in samples if s.endpoint == action], wall_s)
        for action in ACTIONS
        if any(s.endpoint == action for s in samples)
    }
    return LoadResult(
        target="live" if base_url else "in-process",
        concurrency=concurrency,
        users=len(users),
        wall_s=wall_s,
        total=overall.count,
        errors=overall.errors,
        rps=overall.rps,
        overall=overall,
        by_endpoint=by_endpoint,
        weights=weights,
    )


# ------------------------------------------------------------------------ rapport


def format_report(result: LoadResult) -> str:
    lines: list[str] = []
    lines.append("=" * 74)
    lines.append(f"  payment-api — test de charge ({result.target})")
    lines.append("=" * 74)
    lines.append(
        f"  concurrence={result.concurrency}  utilisateurs={result.users}  "
        f"durée={result.wall_s:.2f}s  requêtes={result.total}"
    )
    lines.append(
        f"  débit={result.rps:.1f} req/s   erreurs={result.errors} ({result.error_rate * 100:.2f}%)"
    )
    lines.append("-" * 74)
    header = f"  {'endpoint':<20}{'req':>7}{'err':>6}{'p50':>8}{'p95':>8}{'p99':>8}{'max':>8}"
    lines.append(header)
    lines.append(f"  {'(latences en ms)':<20}")
    for name, st in [("TOTAL", result.overall), *result.by_endpoint.items()]:
        lines.append(
            f"  {name:<20}{st.count:>7}{st.errors:>6}"
            f"{st.p50:>8.1f}{st.p95:>8.1f}{st.p99:>8.1f}{st.max:>8.1f}"
        )
    lines.append("-" * 74)
    lines.append(f"  statuts HTTP : {dict(sorted(result.overall.statuses.items()))}")
    lines.append("=" * 74)
    return "\n".join(lines)


def result_to_dict(result: LoadResult) -> dict:
    def st(s: EndpointStats) -> dict:
        return {
            "count": s.count,
            "errors": s.errors,
            "error_rate": round(s.error_rate, 6),
            "rps": round(s.rps, 2),
            "latency_ms": {
                "p50": round(s.p50, 3),
                "p90": round(s.p90, 3),
                "p95": round(s.p95, 3),
                "p99": round(s.p99, 3),
                "max": round(s.max, 3),
            },
            "statuses": {str(k): v for k, v in sorted(s.statuses.items())},
        }

    return {
        "target": result.target,
        "concurrency": result.concurrency,
        "users": result.users,
        "wall_s": round(result.wall_s, 3),
        "total": result.total,
        "errors": result.errors,
        "error_rate": round(result.error_rate, 6),
        "rps": round(result.rps, 2),
        "weights": result.weights,
        "overall": st(result.overall),
        "by_endpoint": {k: st(v) for k, v in result.by_endpoint.items()},
    }


# ---------------------------------------------------------------------------- CLI


def _parse_weights(spec: str | None, default: dict[str, int]) -> dict[str, int]:
    """Sans `--mix` : le mélange par défaut.

    Avec `--mix` : le spec **définit tout le mélange** — les actions non citées valent 0,
    pour que `--mix "write_transaction=1"` soit réellement « écriture seule ».
    """
    if not spec:
        return default
    weights = dict.fromkeys(ACTIONS, 0)
    for pair in spec.split(","):
        key, _, value = pair.partition("=")
        key = key.strip()
        if key not in ACTIONS:
            raise SystemExit(f"Action inconnue dans --mix : {key!r} (parmi {ACTIONS})")
        weights[key] = int(value)
    if sum(weights.values()) <= 0:
        raise SystemExit("--mix : au moins une action doit avoir un poids > 0.")
    return weights


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="loadgen",
        description="Test de charge payment-api (in-process ASGI par défaut, ou --url live).",
    )
    p.add_argument(
        "--url", help="API cible live (payment-api, ex. http://127.0.0.1:8001). Sinon : in-process."
    )
    p.add_argument(
        "--auth-url",
        help="Service auth pour le login (défaut : --url). À distinguer car /login est servi par auth.",
    )
    p.add_argument(
        "--concurrency", "-c", type=int, default=16, help="Utilisateurs virtuels simultanés."
    )
    p.add_argument(
        "--duration", "-d", type=float, help="Durée en secondes (défaut si ni -d ni -n : 10s)."
    )
    p.add_argument(
        "--requests", "-n", type=int, help="Nombre total de requêtes (prioritaire sur --duration)."
    )
    p.add_argument(
        "--users", type=int, default=5, help="Nombre d'utilisateurs seedés demo01..demoNN."
    )
    p.add_argument(
        "--balance",
        type=int,
        default=10_000_000_000,
        help="Solde initial par compte (centimes, in-process).",
    )
    p.add_argument(
        "--password",
        default="demo-password-demo-password",
        help="Mot de passe des comptes demo (mode --url).",
    )
    p.add_argument(
        "--mix",
        help='Poids des actions, ex. "read_accounts=4,read_transactions=3,write_transaction=3".',
    )
    p.add_argument("--timeout", type=float, default=30.0, help="Timeout par requête (s).")
    p.add_argument("--seed", type=int, default=1234, help="Graine aléatoire (reproductibilité).")
    p.add_argument("--json", dest="json_out", help="Écrit le résultat JSON dans ce fichier.")
    p.add_argument(
        "--max-p95-ms",
        type=float,
        help="Porte SLO : échec (code 2) si p95 global dépasse ce seuil.",
    )
    p.add_argument(
        "--max-error-rate",
        type=float,
        help="Porte SLO : échec (code 2) si le taux d'erreur dépasse ce seuil (0..1).",
    )
    return p


async def _amain(args: argparse.Namespace) -> LoadResult:
    weights = _parse_weights(
        args.mix, {"read_accounts": 4, "read_transactions": 3, "write_transaction": 3}
    )
    duration = args.duration
    if args.requests is not None:
        duration = None  # le volume (--requests) prime sur la durée (--duration)
    elif duration is None:
        duration = 10.0

    if args.url:
        auth_url = args.auth_url or args.url
        users = await discover_live_users(
            auth_url, args.url, args.users, args.password, args.timeout
        )
        return await run_load(
            base_url=args.url,
            users=users,
            concurrency=args.concurrency,
            duration=duration,
            requests=args.requests,
            weights=weights,
            timeout=args.timeout,
            seed=args.seed,
        )

    with tempfile.TemporaryDirectory(prefix="payapi-load-") as tmp:
        db_path = Path(tmp) / "load.db"
        transport, users, engine = build_inprocess(
            args.users, args.balance, args.concurrency, db_path
        )
        try:
            return await run_load(
                transport=transport,
                users=users,
                concurrency=args.concurrency,
                duration=duration,
                requests=args.requests,
                weights=weights,
                timeout=args.timeout,
                seed=args.seed,
            )
        finally:
            await transport.aclose()
            engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = asyncio.run(_amain(args))
    print(format_report(result))

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(result_to_dict(result), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  → JSON écrit dans {args.json_out}")

    breached = []
    if args.max_p95_ms is not None and result.overall.p95 > args.max_p95_ms:
        breached.append(f"p95={result.overall.p95:.1f}ms > {args.max_p95_ms}ms")
    if args.max_error_rate is not None and result.error_rate > args.max_error_rate:
        breached.append(f"taux d'erreur={result.error_rate:.4f} > {args.max_error_rate}")
    if breached:
        print("  ✗ SLO non respectée : " + " ; ".join(breached), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
