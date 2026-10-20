"""waf-exporter — transforme les blocages ModSecurity en métrique et en log normalisé.

Suit le journal d'audit ModSecurity de l'image CRS (format JSON, type Serial), écrit par le WAF
dans un volume partagé (`waf-logs`), et pour chaque transaction bloquée (403 + règle CRS) :
  - incrémente `resilience_waf_blocked_total{rule}` (contrat docs/contracts.md §2), exposée sur
    `GET /metrics` (port 9188, réseau `obs`, scrappée par Prometheus) ;
  - émet un log JSON `waf_blocked` (contrat §1) sur stdout → Promtail/Loki.

Ce sont les deux signaux de l'`incident_type: web_attack` (feature ML `waf_blocked_per_s`,
règle SOC `soc-waf-blocks`).

Usage :
    python waf_exporter.py --audit-log /var/log/modsec/audit.json [--port 9188] [--from-start]

Le fichier peut ne pas exister au démarrage (créé par ModSecurity au premier blocage) : on attend.
Troncature / rotation détectées (taille qui diminue → reprise au début). Par défaut on part de la
FIN du fichier pour ne pas recompter d'anciens blocages après un redémarrage de l'exporteur.
"""

from __future__ import annotations

import argparse
import codecs
import contextlib
import json
import logging
import os
import sys
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from prometheus_client import REGISTRY, CollectorRegistry, Counter, start_http_server

try:  # lib partagée : même objet Counter que les autres services, logger JSON du contrat
    from resilience_common import get_logger
    from resilience_common.metrics import waf_blocked_total as _SHARED_COUNTER
except ImportError:  # pragma: no cover — déployable isolément (tests du parseur sans la lib)
    _SHARED_COUNTER = None

    def get_logger(service: str) -> logging.Logger:  # type: ignore[misc]
        log = logging.getLogger(service)
        if not log.handlers:
            h = logging.StreamHandler(sys.stdout)
            h.setFormatter(logging.Formatter('{"service":"%(name)s","level":"%(levelname)s","message":"%(message)s"}'))
            log.addHandler(h)
        log.setLevel(logging.INFO)
        return log


SERVICE = "waf"
METRIC = "resilience_waf_blocked_total"
DEFAULT_PORT = 9188


@dataclass
class WafBlockEvent:
    """Événement de blocage normalisé (contrat §1)."""

    client_ip: str
    rule: str
    http_path: str
    http_status: int = 403

    def to_log(self) -> dict:
        return {
            "level": "WARNING",
            "service": SERVICE,
            "event": "waf_blocked",
            "message": f"Request blocked by rule {self.rule}",
            "client_ip": self.client_ip,
            "http_path": self.http_path,
            "http_status": self.http_status,
            "rule": self.rule,
        }


# --------------------------------------------------------------------------- parsing
def parse_modsec_record(record: dict) -> WafBlockEvent | None:
    """Transforme un enregistrement d'audit ModSecurity (dict) en événement de blocage, ou None."""
    tx = record.get("transaction", record)
    if not isinstance(tx, dict):
        return None
    messages = tx.get("messages", []) or []
    response = tx.get("response", {}) or {}
    status = response.get("http_code", tx.get("http_status", 0))
    try:
        status = int(status or 0)
    except (TypeError, ValueError):
        return None
    # On ne compte que les requêtes effectivement bloquées (403) avec au moins une règle.
    if status != 403 or not messages:
        return None
    first = messages[0] if isinstance(messages[0], dict) else {}
    details = first.get("details", {}) or {}
    rule = str(details.get("ruleId") or first.get("ruleId") or "unknown")
    request = tx.get("request", {}) or {}
    return WafBlockEvent(
        client_ip=str(tx.get("client_ip", tx.get("remote_address", "unknown"))),
        rule=rule,
        http_path=str(request.get("uri", tx.get("http_path", "/"))),
        http_status=403,
    )


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
    return parse_modsec_record(record) if isinstance(record, dict) else None


MAX_PENDING_BYTES = 1_000_000  # un objet d'audit incomplet plus gros que ça est du bruit : on l'abandonne


def iter_json_objects(chunks: Iterable[str]) -> Iterator[dict]:
    """Décode un flux d'objets JSON concaténés (un par ligne OU collés, avec ou sans retour à la ligne).

    ModSecurity v3 en mode Serial/JSON écrit un objet par transaction ; on ne présume pas de la
    présence d'un `\\n` entre deux objets. Le bruit (texte non JSON) est sauté jusqu'au prochain `{`.
    Un objet jamais refermé (entrée tronquée) ne bloque pas le flux : au-delà de MAX_PENDING_BYTES,
    on repart après son accolade ouvrante.
    """
    decoder = json.JSONDecoder()
    buf = ""
    for chunk in chunks:
        buf += chunk
        while True:
            start = buf.find("{")
            if start < 0:
                buf = ""
                break
            if start:
                buf = buf[start:]  # on ne rescanne jamais le bruit déjà vu
            try:
                obj, end = decoder.raw_decode(buf)
            except json.JSONDecodeError:
                if _looks_incomplete(buf, 0):
                    if len(buf) > MAX_PENDING_BYTES:
                        buf = buf[1:]  # objet jamais refermé : on cherche le suivant
                        continue
                    break  # chunk partiel : on attend la suite
                buf = buf[1:]  # faux départ (accolade dans du bruit)
                continue
            buf = buf[end:]
            if isinstance(obj, dict):
                yield obj


def _looks_incomplete(buf: str, start: int) -> bool:
    """Heuristique : accolades non équilibrées (hors chaînes) => l'objet n'est pas encore complet."""
    depth = 0
    in_str = False
    esc = False
    for ch in buf[start:]:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return False
    return True


def iter_block_events(lines: Iterable[str]) -> Iterator[WafBlockEvent]:
    """Génère les WafBlockEvent à partir d'un itérable de lignes/chunks de log."""
    for record in iter_json_objects(lines):
        event = parse_modsec_record(record)
        if event is not None:
            yield event


# --------------------------------------------------------------------------- exporteur
class WafExporter:
    """Compteur `resilience_waf_blocked_total{rule}` + log `waf_blocked` pour chaque blocage."""

    def __init__(self, registry: CollectorRegistry | None = None, log: logging.Logger | None = None) -> None:
        self.registry = REGISTRY if registry is None else registry
        if registry is None and _SHARED_COUNTER is not None:
            self.counter = _SHARED_COUNTER  # objet partagé avec resilience_common (registre global)
        else:
            self.counter = Counter(METRIC, "Requêtes bloquées par le WAF (exporté depuis les logs ModSec).",
                                   labelnames=("rule",), registry=self.registry)
        self.log = log or get_logger(SERVICE)
        self.seen = 0

    def observe(self, event: WafBlockEvent) -> None:
        self.counter.labels(rule=event.rule).inc()
        self.seen += 1
        payload = event.to_log()
        self.log.warning(payload["message"], extra={
            "event": "waf_blocked", "client_ip": event.client_ip,
            "http_path": event.http_path, "http_status": event.http_status,
        })

    def feed(self, chunks: Iterable[str]) -> int:
        """Consomme un flux de texte ; renvoie le nombre de blocages observés."""
        n = 0
        for event in iter_block_events(chunks):
            self.observe(event)
            n += 1
        return n


def follow(path: Path, *, from_start: bool = False, poll_s: float = 0.5,
           stop: threading.Event | None = None) -> Iterator[str]:
    """`tail -F` minimal : attend le fichier, suit les ajouts, repart du début après troncature.

    Ne garde jamais le fichier ouvert au-delà d'une lecture (compatible avec une rotation qui
    remplace l'inode) ; n'exige aucun droit d'écriture (volume monté en lecture seule).
    Lecture BINAIRE + décodeur incrémental : un caractère UTF-8 coupé entre deux lectures est
    recomposé, et la position est un vrai décalage d'octets comparable à st_size.
    Un fichier absent au démarrage (créé par ModSecurity au premier blocage) est lu depuis
    le début dès son apparition : on ne saute à la fin que pour un fichier déjà présent.
    """
    stop = stop or threading.Event()
    position: int | None = 0 if from_start else None  # None : se placer à la fin du fichier existant
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while not stop.is_set():
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            position = 0  # il n'existe pas encore : tout ce qui y sera écrit est nouveau
            decoder.reset()
            stop.wait(poll_s)
            continue
        if position is None:
            position = size
        if size < position:  # troncature / rotation : on repart du début
            position = 0
            decoder.reset()
        if size > position:
            with path.open("rb") as fh:
                fh.seek(position)
                raw = fh.read()
                position = fh.tell()
            data = decoder.decode(raw)
            if data:
                yield data
            continue
        stop.wait(poll_s)


# --------------------------------------------------------------------------- CLI
def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="waf-exporter RESILIENCE-ALPHA")
    p.add_argument("--audit-log", default=os.environ.get("MODSEC_AUDIT_LOG", "/var/log/modsec/audit.json"),
                   help="journal d'audit ModSecurity (JSON, Serial)")
    p.add_argument("--port", type=int, default=int(os.environ.get("WAF_EXPORTER_PORT", DEFAULT_PORT)))
    p.add_argument("--bind", default=os.environ.get("WAF_EXPORTER_BIND", "0.0.0.0"))
    p.add_argument("--from-start", action="store_true", help="recompter tout le fichier existant")
    p.add_argument("--poll", type=float, default=0.5)
    return p.parse_args(argv)


def main(argv: list[str] | None = None, *, stop: threading.Event | None = None) -> int:
    args = _parse_args(argv)
    exporter = WafExporter()
    start_http_server(args.port, addr=args.bind)
    exporter.log.info(f"waf-exporter démarré : /metrics sur :{args.port}, audit {args.audit_log}")
    with contextlib.suppress(KeyboardInterrupt):
        exporter.feed(follow(Path(args.audit_log), from_start=args.from_start, poll_s=args.poll, stop=stop))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
