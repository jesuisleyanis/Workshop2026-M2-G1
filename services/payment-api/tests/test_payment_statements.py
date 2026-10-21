"""Relevés (#50) : CSV correct, injection neutralisée, période invalide 422, IDOR 404."""

import csv
import io
from datetime import UTC, datetime

import pytest
from paykit import bearer, make_token
from resilience_db.models import Transaction

from payment_api import statements

ST = "/api/v1/statements"
Q = {"account_id": 1, "from": "2026-10-01", "to": "2026-10-31"}


def _tx(src, dst, amount, day, status="created", category="transfer", request_id=None):
    return Transaction(
        src_account=src,
        dst_account=dst,
        amount_cents=amount,
        status=status,
        category=category,
        request_id=request_id,
        created_at=datetime(2026, 10, day, 10, 0, tzinfo=UTC),
    )


@pytest.fixture
def history(db, world):
    db.add_all(
        [
            _tx(1, 3, 1_250, 2, category="food", request_id="req-1"),
            _tx(3, 1, 70_000, 5, category="health"),  # reçu : catégorie de bob masquée
            _tx(1, 3, 99_999, 6, status="rejected"),
            _tx(1, 3, 500, 20, request_id='=HYPERLINK("http://evil")'),
            _tx(1, 3, 100, 31),
            _tx(1, 2, 300, 15),  # vers mon autre compte : débit sur ce relevé
        ]
    )
    db.add(
        Transaction(
            src_account=1,
            dst_account=3,
            amount_cents=1,
            status="created",
            created_at=datetime(2026, 11, 1, 0, 0, tzinfo=UTC),
        )
    )  # hors période
    db.commit()


def _rows(text):
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text[1:]), delimiter=";"))


def test_csv_download_headers_and_content(client, alice, history):
    r = client.get(ST, headers=alice, params=Q)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == (
        'attachment; filename="releve-1-2026-10-01-2026-10-31.csv"'
    )
    rows = _rows(r.text)
    assert rows[0] == list(statements.HEADER)
    assert len(rows) == 1 + 6, "bornes incluses (01 et 31), 01/11 exclu"
    first = dict(zip(rows[0], rows[1], strict=True))
    assert first == {
        "Date": "2026-10-02 10:00",
        "Référence": "req-1",
        "Libellé": "Virement vers le compte n°3",
        "Catégorie": "Alimentation",
        "Débit": "12,50",
        "Crédit": "",
        "Statut": "Effectué",
    }
    received = dict(zip(rows[0], rows[2], strict=True))
    assert (received["Crédit"], received["Catégorie"]) == ("700,00", ""), (
        "catégorie de l'émetteur masquée"
    )
    assert dict(zip(rows[0], rows[3], strict=True))["Statut"] == "Refusé"


def test_csv_injection_is_neutralised(client, alice, history):
    rows = _rows(client.get(ST, headers=alice, params=Q).text)
    refs = [r[1] for r in rows[1:]]
    assert '\'=HYPERLINK("http://evil")' in refs
    for cell in (c for r in rows[1:] for c in r):
        assert not cell.startswith(("=", "+", "-", "@", "\t", "\r")), cell


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"])
def test_safe_cell_prefixes_every_formula_trigger(value):
    assert statements.safe_cell(value) == "'" + value
    assert statements.safe_cell("Virement") == "Virement"


def test_json_format_for_the_printable_page(client, alice, history):
    body = client.get(ST, headers=alice, params={**Q, "format": "json"}).json()
    assert (body["account_id"], body["holder"], body["from"], body["to"]) == (
        1,
        "alice",
        "2026-10-01",
        "2026-10-31",
    )
    assert body["total_debit_cents"] == 1_250 + 500 + 100 + 300, "refus exclus des totaux"
    assert body["total_credit_cents"] == 70_000
    assert [r["direction"] for r in body["rows"]][:2] == ["debit", "credit"]
    assert body["rows"][1]["category"] is None


@pytest.mark.parametrize(
    "params",
    [
        {**Q, "from": "2026-10-31", "to": "2026-10-01"},
        {**Q, "from": "2025-10-01", "to": "2026-10-31"},
        {**Q, "from": "2025-01-01", "to": "2026-01-02"},  # 367 jours inclus
        {**Q, "from": "9999-06-01", "to": "9999-12-31"},  # pas de débordement (500)
        {**Q, "from": "1999-12-31", "to": "2000-01-05"},
    ],
)
def test_invalid_period_is_422(client, alice, params):
    r = client.get(ST, headers=alice, params=params)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_period"


@pytest.mark.parametrize(
    "params", [{**Q, "format": "pdf"}, {**Q, "from": "nope"}, {"account_id": 1}]
)
def test_malformed_query_is_validation_error(client, alice, params):
    r = client.get(ST, headers=alice, params=params)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_idor_other_users_account_is_404(client, history):
    r = client.get(ST, headers=bearer(make_token("bob")), params=Q)
    assert r.status_code == 404 and r.json()["error"]["code"] == "account_not_found"


def test_volume_is_bounded(client, alice, history, monkeypatch):
    monkeypatch.setattr(statements, "MAX_ROWS", 3)
    r = client.get(ST, headers=alice, params=Q)
    assert r.status_code == 422 and r.json()["error"]["code"] == "statement_too_large"


def test_export_is_audited_and_needs_a_bearer(client, alice, history, log_lines):
    client.get(ST, headers=alice, params=Q)
    (e,) = log_lines("statement_exported")
    assert e["user"] == "alice" and "6 rows" in e["message"]
    assert client.get(ST, params=Q).status_code == 401


def test_a_full_year_inclusive_is_accepted(client, alice, history):
    r = client.get(ST, headers=alice, params={**Q, "from": "2025-11-01", "to": "2026-10-31"})
    assert r.status_code == 200, "365 jours inclus"


def test_third_party_refusals_never_appear_on_the_recipient_statement(client, db, history):
    db.add(_tx(3, 1, 5_000, 12, status="rejected"))  # bob échoue un virement vers alice
    db.commit()
    body = client.get(
        ST, headers=bearer(make_token("alice")), params={**Q, "format": "json"}
    ).json()
    assert not [r for r in body["rows"] if r["direction"] == "credit" and r["status"] == "rejected"]
    bob_q = {**Q, "account_id": 3, "format": "json"}
    bob = client.get(ST, headers=bearer(make_token("bob")), params=bob_q).json()
    assert any(r["status"] == "rejected" for r in bob["rows"]), "l'émetteur voit son propre refus"
