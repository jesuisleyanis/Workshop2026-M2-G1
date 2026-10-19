#!/usr/bin/env python3
"""gen_normal_traffic.py — trafic LÉGITIME réaliste contre la plateforme (via le WAF).

Deux usages, le même profil (c'est voulu : le modèle doit avoir vu à l'entraînement
le normal qu'il verra pendant la démo) :
  1. capture de la baseline réelle pour ré-entraîner le modèle (`make capture-baseline`) ;
  2. temps 1 de la démo (« avant l'incident ») et bruit de fond pendant l'attaque.

Profil : des clients fictifs (comptes de scripts/seed.py) qui se connectent, consultent
leurs comptes et leur historique, font de petits virements croisés, avec ~2 % de fautes
de saisie (mauvais mot de passe, virement vers un compte inexistant). Le débit suit un
cycle lent (± AMPLITUDE autour de --rps) pour que la baseline couvre plusieurs niveaux
de charge. Les logins restent rares : sous la limite de l'auth (10/min/IP par défaut),
sinon on fabriquerait des 429 qui n'existent pas dans le vrai normal.
Deux garde-fous le garantissent même quand l'auth tombe (redémarrage par la remédiation,
429, 5xx) : un budget de logins PARTAGÉ (8/min, fenêtre glissante) et une pause exponentielle
par client après un login en échec (5 s -> 60 s, Retry-After respecté). Sans eux, un client
sans jeton relancerait un login à chaque tour : une avalanche qui ressemble à une attaque.

    python3 scripts/gen_normal_traffic.py --duration 60m [--rps 5] [--base-url https://localhost]

Stdlib uniquement (lancé depuis le poste hôte, comme verify_tx). Ctrl-C = arrêt propre.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field

BASE_URL = os.environ.get("BASE_URL", "https://localhost")
TIMEOUT = 5.0
#: Comptes fictifs créés par scripts/seed.py : (utilisateur, mot de passe).
USERS = [
    ("demo01", "demo-pass-01"),
    ("demo02", "demo-pass-02"),
    ("ops", "ops-pass-00"),
]
#: Identifiant de compte qui n'existe pas (payment-api répond 404 destination_not_found).
UNKNOWN_ACCOUNT = 999_999
#: Répartition des actions d'un client connecté (somme = 1).
#: bad_login reste très rare : à 5 req/s, 0,5 % = 1,5 login raté/min, qui s'ajoutent aux
#: re-logins (~0,6/min) sous la limite de 10 logins/min/IP de l'auth.
ACTIONS = (
    ("accounts", 0.415),
    ("history", 0.35),
    ("transfer", 0.20),
    ("bad_transfer", 0.03),   # compte destinataire inexistant -> 4xx légitime
    ("bad_login", 0.005),     # faute de frappe sur le mot de passe -> 401 légitime
)
AMPLITUDE = 0.3          # ± 30 % autour du débit moyen
CYCLE_S = 600.0          # période du cycle de charge
SESSION_TTL_S = 300.0    # re-login toutes les ~5 min par client
#: Pause après un login en échec (auth redémarrée, 429, 5xx) : 5 s, 10 s, 20 s... plafonnée.
#: Sans elle, un client sans jeton relancerait un login à CHAQUE tour (~100/min à 5 req/s) :
#: une avalanche de 429 qui ressemble à une attaque par force brute.
BACKOFF_BASE_S = 5.0
BACKOFF_MAX_S = 60.0
BACKOFF_JITTER = 0.2     # ± 20 % pour désynchroniser les clients
#: Budget de logins PARTAGÉ par tous les clients : la limite de l'auth (10/min) est par IP,
#: et tout le générateur sort de la même IP. 8 laisse de la marge (verify_tx, humain).
LOGIN_BUDGET_PER_MIN = 8

log = logging.getLogger("gen_normal_traffic")

_CTX = ssl.create_default_context()
_CTX.check_hostname = False   # certificat auto-signé du WAF (labo fermé)
_CTX.verify_mode = ssl.CERT_NONE


def parse_duration(text: str) -> float:
    m = re.fullmatch(r"(\d+)([smh])", text.strip())
    if not m:
        raise ValueError(f"durée invalide {text!r} (ex. 90s, 30m, 2h)")
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2)]


def target_rate(elapsed_s: float, rps: float, amplitude: float = AMPLITUDE,
                cycle_s: float = CYCLE_S) -> float:
    """Débit cible (req/s) à l'instant `elapsed_s` : cycle sinusoïdal lent autour de rps."""
    return max(0.1, rps * (1.0 + amplitude * math.sin(2 * math.pi * elapsed_s / cycle_s)))


def pick_action(rng: random.Random) -> str:
    r, acc = rng.random(), 0.0
    for name, weight in ACTIONS:
        acc += weight
        if r < acc:
            return name
    return ACTIONS[0][0]


def http(method: str, path: str, payload: dict | None = None, token: str | None = None,
         base_url: str = BASE_URL) -> tuple[int, dict | list]:
    """Requête vers le WAF ; (code HTTP, corps JSON). Code 0 = injoignable. Ne lève jamais."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        # Retry-After (429/503) remonté dans le corps : seul en-tête utile au client.
        retry_after = (exc.headers or {}).get("Retry-After")
        return exc.code, ({"retry_after": retry_after} if retry_after else {})
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError, ValueError):
        return 0, {}


class LoginBudget:
    """Fenêtre glissante de 60 s sur les logins (réussis, ratés ou fautes de frappe)."""

    def __init__(self, per_min: int = LOGIN_BUDGET_PER_MIN) -> None:
        self.per_min = per_min
        self.times: deque[float] = deque()

    def _trim(self, now: float) -> None:
        while self.times and now - self.times[0] >= 60.0:
            self.times.popleft()

    def allow(self, now: float) -> bool:
        self._trim(now)
        return len(self.times) < self.per_min

    def record(self, now: float) -> None:
        self.times.append(now)

    def next_slot(self, now: float) -> float:
        """Premier instant où un login sera de nouveau autorisé."""
        return now if self.allow(now) else self.times[0] + 60.0


@dataclass
class Client:
    """Un utilisateur fictif, sa session et l'id de son compte (lu via GET /accounts)."""

    username: str
    password: str
    send: Callable[..., tuple[int, dict | list]] = field(default=http, repr=False)  # injectable
    peers: list[Client] = field(default_factory=list, repr=False)  # contreparties possibles
    token: str | None = None
    logged_at: float = -math.inf
    account_id: int | None = None
    retry_at: float = -math.inf   # pas de login avant cet instant (pause après échec)
    login_failures: int = 0
    budget: LoginBudget | None = field(default=None, repr=False)  # partagé entre clients

    def login(self, now: float, password: str | None = None,
              rng: random.Random | None = None) -> int:
        """Login. Avec `password` (faute de frappe volontaire), aucun effet sur la session."""
        if self.budget is not None:
            self.budget.record(now)
        status, body = self.send("POST", "/api/v1/login",
                                 {"username": self.username, "password": password or self.password})
        if password is not None:
            return status
        if status == 200 and isinstance(body, dict):
            self.token = body.get("access_token") or body.get("token")
            self.logged_at = now
            self.login_failures = 0
        else:
            self._back_off(now, status, body, rng or random.Random())
        return status

    def _back_off(self, now: float, status: int, body: dict | list, rng: random.Random) -> None:
        self.login_failures += 1
        delay = min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** (self.login_failures - 1))
        delay *= rng.uniform(1 - BACKOFF_JITTER, 1 + BACKOFF_JITTER)
        try:
            retry_after = float(body.get("retry_after", 0)) if isinstance(body, dict) else 0.0
        except (TypeError, ValueError):
            retry_after = 0.0
        self.retry_at = now + max(delay, retry_after)
        log.warning("%s : login en échec (HTTP %s), pause %.0f s", self.username, status,
                    self.retry_at - now)

    def needs_login(self, now: float) -> bool:
        return self.token is None or now - self.logged_at > SESSION_TTL_S

    def ready(self, now: float) -> bool:
        """Peut agir maintenant : pas en pause, et budget de logins dispo s'il doit se connecter."""
        if now < self.retry_at:
            return False
        return not (self.needs_login(now) and self.budget and not self.budget.allow(now))

    def wake_at(self, now: float) -> float:
        wake = self.retry_at
        if self.needs_login(now) and self.budget is not None:
            wake = max(wake, self.budget.next_slot(now))
        return wake

    def list_accounts(self) -> int:
        status, body = self.send("GET", "/api/v1/accounts", token=self.token)
        if status == 200 and isinstance(body, list) and body:
            self.account_id = int(body[0]["id"])
        return status

    def transfer(self, rng: random.Random, dst: int) -> int:
        status, _ = self.send("POST", "/api/v1/transactions",
                              {"src_account": self.account_id, "dst_account": dst,
                               "amount_cents": rng.randint(1, 500)}, token=self.token)
        return status

    def step(self, rng: random.Random, now: float) -> tuple[str, int]:
        """Joue une action ; (re)connecte d'abord si la session a expiré.

        À n'appeler que si `ready(now)` : pendant une pause après échec, le client se tait.
        """
        if self.needs_login(now):
            return "login", self.login(now, rng=rng)
        action = pick_action(rng)
        if action == "bad_login" and self.budget is not None and not self.budget.allow(now):
            action = "history"  # pas de faute de frappe si le budget de logins est épuisé
        peers = [p.account_id for p in self.peers if p.account_id not in (None, self.account_id)]
        if action in ("transfer", "bad_transfer") and (self.account_id is None or not peers):
            action = "accounts"  # compte (ou contrepartie) pas encore connu : on le consulte
        if action == "accounts":
            status = self.list_accounts()
        elif action == "history":
            status, _ = self.send("GET", "/api/v1/transactions", token=self.token)
        elif action == "transfer":
            status = self.transfer(rng, rng.choice(peers))
        elif action == "bad_transfer":
            status = self.transfer(rng, UNKNOWN_ACCOUNT)
        else:
            status = self.login(now, password=self.password + "x")
        if status == 401 and action != "bad_login":
            self.token = None  # jeton expiré : re-login au prochain tour
        return action, status


def run(duration_s: float, rps: float, send: Callable[..., tuple[int, dict]], seed: int = 0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> Counter:
    """Boucle principale (mono-thread, arrivées de Poisson) ; renvoie les compteurs."""
    rng = random.Random(seed)
    budget = LoginBudget()
    clients = [Client(u, p, send=send, budget=budget) for u, p in USERS]
    for c in clients:
        c.peers = clients
    stats: Counter = Counter()
    start = clock()
    next_report = start + 30
    while (now := clock()) - start < duration_s:
        ready = [c for c in clients if c.ready(now)]
        if not ready:  # tous en pause (auth indisponible) : on attend le premier réveil
            stats["wait"] += 1
            sleep(max(0.1, min(c.wake_at(now) for c in clients) - now))
            continue
        client = rng.choice(ready)
        action, status = client.step(rng, now)
        stats[f"{action}:{status}"] += 1
        stats["total"] += 1
        if now >= next_report:
            log.info("t=%ds cible=%.1f req/s total=%d codes=%s", int(now - start),
                     target_rate(now - start, rps), stats["total"],
                     dict(sorted((k, v) for k, v in stats.items() if k not in ("total", "wait"))))
            next_report = now + 30
        sleep(rng.expovariate(target_rate(now - start, rps)))
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
                        stream=sys.stderr)
    p = argparse.ArgumentParser(description="Trafic légitime réaliste (baseline / démo)")
    p.add_argument("--duration", default="60m", help="durée (ex. 60m, 2h)")
    p.add_argument("--rps", type=float, default=5.0, help="débit moyen (req/s)")
    p.add_argument("--base-url", default=BASE_URL)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)
    def send(method, path, payload=None, token=None):
        return http(method, path, payload, token, base_url=args.base_url)

    try:
        stats = run(parse_duration(args.duration), args.rps, send, args.seed)
    except KeyboardInterrupt:
        log.info("arrêt demandé")
        return 0
    if stats["total"] and sum(v for k, v in stats.items() if k.endswith(":0")) == stats["total"]:
        log.error("plateforme injoignable sur %s (make up ? make seed ?)", args.base_url)
        return 1
    log.info("terminé : %d requêtes", stats["total"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
