"""Relevés de compte (#50) : `GET /api/v1/statements` en CSV (téléchargement) ou JSON (impression).

Sécurité : compte possédé uniquement (sinon 404), période bornée (366 jours), volume borné
(MAX_ROWS : les comptes de service reçoivent ~1 virement/s du trafic normal), et injection CSV
neutralisée — toute cellule commençant par = + - @ tabulation ou CR est préfixée d'une apostrophe.
Les montants sont NON signés (colonnes Débit / Crédit) : aucun « -12,50 » à neutraliser.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, time, timedelta

from resilience_db.models import Account, Transaction, User
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from payment_api.ledger import Rejection

MAX_DAYS = 366  # bornes incluses : au plus un an
EARLIEST, LATEST = date(2000, 1, 1), date(2100, 12, 31)  # pas de débordement de date
MAX_ROWS = 5_000
HEADER = ("Date", "Référence", "Libellé", "Catégorie", "Débit", "Crédit", "Statut")
CATEGORY_FR = {
    "food": "Alimentation",
    "shopping": "Shopping",
    "transport": "Transport",
    "subscriptions": "Abonnements",
    "health": "Santé",
    "leisure": "Loisirs",
    "housing": "Logement",
    "transfer": "Virement",
    "other": "Autre",
}
_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: str) -> str:
    """Neutralise l'injection de formule (CSV/DDE) dans Excel, LibreOffice, Sheets."""
    return "'" + value if value.startswith(_DANGEROUS) else value


def _amount(cents: int) -> str:
    return f"{cents // 100}," + f"{cents % 100:02d}"


def build(session: Session, user: User, account_id: int, start: date, end: date) -> dict:
    if not EARLIEST <= start <= end <= LATEST or (end - start).days + 1 > MAX_DAYS:
        raise Rejection(422, "invalid_period", "Period must be ordered and at most 12 months")
    account = session.get(Account, account_id)
    if account is None or account.user_id != user.id:
        raise Rejection(404, "account_not_found", "Account not found")
    lo = datetime.combine(start, time.min, tzinfo=UTC)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
    txs = session.scalars(
        select(Transaction)
        .where(
            or_(
                Transaction.src_account == account.id,
                # Reçus aboutis seulement (en SQL : les refus d'un tiers ne comptent pas non plus
                # dans MAX_ROWS — sinon n'importe qui pourrait rendre un relevé « trop gros »).
                and_(Transaction.dst_account == account.id, Transaction.status == "created"),
            ),
            Transaction.created_at >= lo,
            Transaction.created_at < hi,
        )
        .order_by(Transaction.created_at, Transaction.id)
        .limit(MAX_ROWS + 1)
    ).all()
    if len(txs) > MAX_ROWS:
        raise Rejection(422, "statement_too_large", "Too many operations: shorten the period")
    rows, debit, credit = [], 0, 0
    for t in txs:
        out = t.src_account == account.id
        if t.status == "created":
            if out:
                debit += t.amount_cents
            else:
                credit += t.amount_cents
        rows.append(
            {
                "id": t.id,
                "created_at": t.created_at
                if t.created_at.tzinfo
                else t.created_at.replace(tzinfo=UTC),
                # Référence de l'émetteur masquée sur un crédit (id de programmation, périodicité).
                "reference": (t.request_id if out else None) or f"#{t.id}",
                "direction": "debit" if out else "credit",
                "counterparty_account": t.dst_account if out else t.src_account,
                # Catégorie de l'émetteur : jamais divulguée au destinataire (#44).
                "category": t.category if out else None,
                "amount_cents": t.amount_cents,
                "status": t.status,
            }
        )
    return {
        "account_id": account.id,
        "iban_fake": account.iban_fake,
        "holder": user.username,
        "from": start,
        "to": end,
        "rows": rows,
        "total_debit_cents": debit,
        "total_credit_cents": credit,
    }


def to_csv(statement: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(HEADER)
    for r in statement["rows"]:
        out = r["direction"] == "debit"
        label = ("Virement vers le compte n°" if out else "Virement du compte n°") + str(
            r["counterparty_account"]
        )
        w.writerow(
            safe_cell(str(c))
            for c in (
                r["created_at"].astimezone(UTC).strftime("%Y-%m-%d %H:%M"),
                r["reference"],
                label,
                CATEGORY_FR.get(r["category"], "") if r["category"] else "",
                _amount(r["amount_cents"]) if out else "",
                "" if out else _amount(r["amount_cents"]),
                "Effectué" if r["status"] == "created" else "Refusé",
            )
        )
    return "﻿" + buf.getvalue()  # BOM : accents corrects à l'ouverture dans Excel
