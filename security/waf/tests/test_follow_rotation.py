"""Suivi du journal d'audit face aux troncatures et rotations (waf_exporter.follow).

Le journal vit dans un tmpfs borné par un script de troncature côté WAF (97-audit-rotate.sh) :
l'exporter ne doit ni perdre les blocages suivants ni relire du contenu au milieu d'une ligne.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from waf_exporter import follow  # noqa: E402


def _record(n: int, ip: str = "192.168.137.50") -> str:
    """Une transaction de la forme du journal (le début de la ligne varie : IP, horodatage)."""
    return json.dumps({"transaction": {"client_ip": ip, "time_stamp": f"Mon Oct 19 10:00:{n:02d} 2026",
                                       "unique_id": f"id-{n:04d}", "request": {"uri": "/x"},
                                       "response": {"http_code": 403}, "messages": [{"details": {"ruleId": "942100"}}]}})


def _script(*steps):
    pending = list(steps)
    state = {"done": False}

    def sleep(_):
        if pending:
            pending.pop(0)()
        else:
            state["done"] = True

    return sleep, (lambda: state["done"])


def _append(path: Path, *records: str) -> None:
    with path.open("ab") as fh:
        for r in records:
            fh.write(r.encode() + b"\n")


def test_truncate_then_regrow_past_the_old_position_is_detected(tmp_path):
    """Régression : la détection par taille seule (taille < position) ne voyait pas un fichier
    tronqué puis ré-alimenté au-delà de l'ancienne position entre deux sondages -> lecture au
    milieu de la nouvelle ligne, blocages perdus."""
    log = tmp_path / "audit.json"
    log.write_bytes(b"")
    first = [_record(1), _record(2)]

    def write_initial():
        _append(log, *first)

    def truncate_and_regrow_bigger():
        log.write_bytes(b"")                                  # troncature (script de rotation)
        _append(log, *[_record(n, ip="10.9.9.9") for n in range(10, 16)])   # plus long que l'ancien contenu
        assert log.stat().st_size > sum(len(r) + 1 for r in first)

    sleep, stop = _script(write_initial, truncate_and_regrow_bigger)
    lines = list(follow(str(log), from_end=True, poll_s=0, should_stop=stop, sleep=sleep))
    assert lines[:2] == first
    assert lines[2:] == [_record(n, ip="10.9.9.9") for n in range(10, 16)]    # tout, depuis le début, lignes entières
    assert all(json.loads(line) for line in lines)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows interdit de renommer un fichier ouvert (le WAF tourne sous Linux)")
def test_rotation_by_rename_restarts_at_the_beginning_of_the_new_file(tmp_path):
    log = tmp_path / "audit.json"
    log.write_bytes(b"")

    def write_old():
        _append(log, _record(1))

    def rotate():
        log.rename(tmp_path / "audit.json.1")
        _append(log, _record(2), _record(3))

    sleep, stop = _script(write_old, rotate)
    lines = list(follow(str(log), from_end=True, poll_s=0, should_stop=stop, sleep=sleep))
    assert lines == [_record(1), _record(2), _record(3)]


def test_growing_file_is_not_mistaken_for_a_replacement(tmp_path):
    """Un journal qui s'allonge garde le même début : aucune relecture, aucun doublon."""
    log = tmp_path / "audit.json"
    log.write_bytes(b"")

    def step(n):
        return lambda: _append(log, _record(n))

    sleep, stop = _script(*[step(n) for n in range(1, 6)])
    lines = list(follow(str(log), from_end=True, poll_s=0, should_stop=stop, sleep=sleep))
    assert lines == [_record(n) for n in range(1, 6)]


def test_file_created_empty_then_filled_keeps_every_line(tmp_path):
    log = tmp_path / "audit.json"

    def create_empty():
        log.write_bytes(b"")

    def fill():
        _append(log, _record(1), _record(2))

    sleep, stop = _script(create_empty, fill)
    assert list(follow(str(log), from_end=True, poll_s=0, should_stop=stop, sleep=sleep)) == [_record(1), _record(2)]


def test_crlf_and_invalid_utf8_do_not_break_the_stream(tmp_path):
    log = tmp_path / "audit.json"
    log.write_bytes(b"")

    def write():
        with log.open("ab") as fh:
            fh.write(b"ligne\r\n\xff\xfe cass\xc3\xa9e\nfin\n")

    sleep, stop = _script(write)
    lines = list(follow(str(log), from_end=True, poll_s=0, should_stop=stop, sleep=sleep))
    assert lines == ["ligne", "�� cassée", "fin"]
