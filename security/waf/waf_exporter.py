"""waf-exporter — transforme les blocages ModSecurity en métrique et en log normalisé.

Suit en continu (comme `tail -F`) le journal d'audit ModSecurity (JSON, une transaction
par ligne) écrit par le conteneur waf dans le volume partagé `waf-logs`, et pour chaque
requête BLOQUÉE (403 avec au moins une règle) :
  * incrémente `resilience_waf_blocked_total{rule}` (docs/contracts.md §2), exposée sur
    /metrics (port 9188, scrapée par Prometheus ; alimente `waf_blocked_per_s` du ML) ;
  * écrit sur stdout le log JSON `waf_blocked` (contrat §1), récupéré par Promtail -> Loki
    (fonction SOC, action de remédiation `confirm_waf_block`).

Service à part (et non un second processus dans le conteneur waf) : il tourne en
lecture seule, sans réseau d'entrée exposé, et n'a besoin que du volume de logs.

Usage :
    python waf_exporter.py --audit-log /var/log/modsec/audit.json [--port 9188]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO, TextIO

#: Règles d'évaluation/corrélation du CRS : elles disent « score dépassé », pas « quelle
#: attaque ». On leur préfère la première règle de détection pour le label `rule`.
CRS_EVALUATION_RULES = frozenset({"949110", "959100", "980130", "980140", "980170"})
#: Règles de conformité protocole (920xxx) : signal faible, utilisé seulement à défaut.
PROTOCOL_RULE_PREFIX = "920"


@dataclass
class WafBlockEvent:
    """Événement de blocage normalisé (contrat §1)."""

    client_ip: str
    rule: str
    http_path: str
    http_status: int = 403

    def to_log(self, ts: str | None = None) -> dict:
        return {
            "ts": ts or _now_iso(),
            "level": "WARNING",
            "service": "waf",
            "event": "waf_blocked",
            "message": f"Request blocked by rule {self.rule}",
            "request_id": None,
            "client_ip": self.client_ip,
            "http_path": self.http_path,
            "http_status": self.http_status,
            "rule": self.rule,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _rule_id(message: dict) -> str:
    details = message.get("details") if isinstance(message.get("details"), dict) else {}
    return str(details.get("ruleId") or message.get("ruleId") or "")


def pick_rule(messages: list[dict]) -> str:
    """Règle la plus parlante : détection > protocole > évaluation du score."""
    ids = [r for r in (_rule_id(m) for m in messages) if r]
    for candidates in (
        [r for r in ids if r not in CRS_EVALUATION_RULES and not r.startswith(PROTOCOL_RULE_PREFIX)],
        [r for r in ids if r not in CRS_EVALUATION_RULES],
        ids,
    ):
        if candidates:
            return candidates[0]
    return "unknown"


def parse_modsec_line(line: str) -> WafBlockEvent | None:
    """Parse une ligne d'audit ModSecurity (JSON) et renvoie un événement de blocage.

    Renvoie None si la ligne ne correspond pas à un blocage (action != deny / 403).
    Tolérant : ignore les lignes non-JSON.
    """
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None

    # Structure inattendue (champ non-objet...) -> ligne ignorée, jamais une exception :
    # un crash de l'exporter ferait perdre les blocages pendant son redémarrage.
    tx = record.get("transaction", record)
    if not isinstance(tx, dict):
        return None
    messages = [m for m in tx.get("messages") or [] if isinstance(m, dict)]
    response = tx.get("response") if isinstance(tx.get("response"), dict) else {}
    request = tx.get("request") if isinstance(tx.get("request"), dict) else {}
    status = response.get("http_code", tx.get("http_status", 0))

    # On ne compte que les requêtes effectivement bloquées (403) avec au moins une règle.
    try:
        blocked = int(status or 0) == 403
    except (TypeError, ValueError):
        return None
    if not blocked or not messages:
        return None

    uri = str(request.get("uri", tx.get("http_path", "/")))
    return WafBlockEvent(
        client_ip=str(tx.get("client_ip", tx.get("remote_address", "unknown"))),
        rule=pick_rule(messages),
        # Chemin seul : la query string porte souvent la charge d'attaque elle-même.
        http_path=uri.split("?", 1)[0] or "/",
        http_status=403,
    )


def iter_block_events(lines: Iterable[str]) -> Iterator[WafBlockEvent]:
    """Génère les WafBlockEvent à partir d'un itérable de lignes de log."""
    for line in lines:
        event = parse_modsec_line(line)
        if event is not None:
            yield event


#: Octets du début du fichier mémorisés pour reconnaître un fichier tronqué puis ré-alimenté.
HEAD_BYTES = 256


def _was_replaced(path: str, inode: int, pos: int, head: bytes) -> tuple[bool, bytes]:
    """Le fichier suivi a-t-il été remplacé ou tronqué ? Renvoie aussi le début à retenir.

    Trois indices : autre inode (rotation par renommage), taille < position (troncature
    vue avant ré-alimentation) et DÉBUT DU FICHIER DIFFÉRENT. Ce dernier couvre la troncature
    suivie d'une ré-alimentation au-delà de l'ancienne position entre deux sondages, que la
    seule comparaison des tailles ne voit pas (un flot de blocages pourrait la provoquer).
    Un journal ModSecurity n'est qu'ajouté : son début ne change jamais tant qu'il n'est pas
    tronqué ; il s'allonge seulement (les premières transactions portent IP et horodatage).
    """
    try:
        st = os.stat(path)
        if st.st_ino != inode or st.st_size < pos:
            return True, head
        with open(path, "rb") as fh:
            current = fh.read(HEAD_BYTES)
    except FileNotFoundError:
        return True, head
    if current[: len(head)] != head:
        return True, head
    return False, current if len(current) > len(head) else head


def follow(path: str, *, from_end: bool = True, poll_s: float = 0.5,
           should_stop: Callable[[], bool] = lambda: False,
           sleep: Callable[[float], None] = time.sleep) -> Iterator[str]:
    """Lignes ajoutées à `path`, comme `tail -F`.

    Attend que le fichier existe (le waf le crée à la 1re transaction journalisée),
    reprend au début s'il est tronqué ou remplacé (rotation, voir `_was_replaced`), ne rend
    que des lignes complètes. `from_end` : ignorer l'existant au démarrage (pas de double
    comptage après un redémarrage — Prometheus gère la remise à zéro du compteur).
    """
    fh: BinaryIO | None = None
    inode = 0
    head = b""
    buf = b""
    try:
        while not should_stop():
            if fh is None:
                try:
                    fh = open(path, "rb")  # noqa: SIM115
                except FileNotFoundError:
                    # Absent : le fichier sera créé par la prochaine transaction journalisée,
                    # qu'il ne faut pas sauter -> lecture depuis le début une fois apparu.
                    from_end = False
                    sleep(poll_s)
                    continue
                inode = os.fstat(fh.fileno()).st_ino
                head = fh.read(HEAD_BYTES)
                fh.seek(0, os.SEEK_END if from_end else os.SEEK_SET)
                from_end = False  # un fichier (re)créé ensuite est lu depuis le début
            replaced, head = _was_replaced(path, inode, fh.tell(), head)
            if replaced:
                fh.close()
                fh, buf, head = None, b"", b""
                continue
            chunk = fh.read()
            if chunk:
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for raw in lines:
                    yield raw.rstrip(b"\r").decode("utf-8", errors="replace")
                continue
            sleep(poll_s)
    finally:
        if fh is not None:
            fh.close()


def run(lines: Iterable[str], counter, out: TextIO = sys.stdout) -> int:
    """Compte et journalise chaque blocage ; renvoie le nombre traité."""
    n = 0
    for event in iter_block_events(lines):
        counter.labels(rule=event.rule).inc()
        out.write(json.dumps(event.to_log(), ensure_ascii=False) + "\n")
        out.flush()
        n += 1
    return n


def make_counter(registry=None):
    from prometheus_client import REGISTRY, Counter

    # Nom et label figés par docs/contracts.md §2.
    return Counter("resilience_waf_blocked_total", "Requêtes bloquées par le WAF (ModSecurity/CRS)",
                   ["rule"], registry=registry if registry is not None else REGISTRY)


def main(argv: list[str] | None = None) -> int:
    from prometheus_client import start_http_server

    p = argparse.ArgumentParser(description="ModSecurity audit log -> resilience_waf_blocked_total")
    p.add_argument("--audit-log", default=os.getenv("WAF_AUDIT_LOG", "/var/log/modsec/audit.json"))
    p.add_argument("--port", type=int, default=int(os.getenv("WAF_EXPORTER_PORT", "9188")))
    p.add_argument("--from-start", action="store_true", help="relire tout le journal existant")
    args = p.parse_args(argv)

    counter = make_counter()
    start_http_server(args.port)
    # Pas d'event de démarrage : les noms d'events sont réservés par le contrat §1.
    run(follow(args.audit_log, from_end=not args.from_start), counter)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
