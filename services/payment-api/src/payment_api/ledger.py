"""Règles métier du virement fictif. Pas de HTTP ici : lève `Rejection`, renvoie une Transaction."""

from __future__ import annotations

from resilience_db.models import Account, Transaction, TransactionStatus, User
from sqlalchemy import select
from sqlalchemy.orm import Session

MAX_AMOUNT_CENTS = 100_000_000  # 1 000 000,00 EUR fictifs


class Rejection(Exception):
    """Virement refusé pour une raison métier (-> event transaction_rejected)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def transfer(
    session: Session,
    user: User,
    src_id: int,
    dst_id: int,
    amount_cents: int,
    request_id: str | None,
) -> Transaction:
    """Débite `src_id` (qui doit appartenir à `user`) et crédite `dst_id`, atomiquement."""
    if amount_cents <= 0:
        raise Rejection(422, "invalid_amount", "Amount must be strictly positive")
    if amount_cents > MAX_AMOUNT_CENTS:
        raise Rejection(422, "amount_too_large", "Amount exceeds the maximum allowed")
    if src_id == dst_id:
        raise Rejection(422, "same_account", "Source and destination must differ")

    # Verrou de ligne dans l'ordre des id : pas de deadlock entre deux virements croisés,
    # et le contrôle de solde se fait sous verrou (pas de double dépense concurrente).
    rows = session.scalars(
        select(Account)
        .where(Account.id.in_((src_id, dst_id)))
        .order_by(Account.id)
        .with_for_update()
    ).all()
    accounts = {a.id: a for a in rows}
    src, dst = accounts.get(src_id), accounts.get(dst_id)

    # Source inexistante OU appartenant à autrui : même réponse (pas d'oracle d'existence).
    if src is None or src.user_id != user.id:
        raise Rejection(404, "account_not_found", "Source account not found")
    if dst is None:
        raise Rejection(404, "destination_not_found", "Destination account not found")
    if src.currency != dst.currency:
        raise Rejection(422, "currency_mismatch", "Accounts use different currencies")

    if src.balance_cents < amount_cents:
        # Tentative traçable : on persiste la transaction refusée (R2), sans toucher aux soldes.
        session.add(
            Transaction(
                src_account=src.id,
                dst_account=dst.id,
                amount_cents=amount_cents,
                status=TransactionStatus.REJECTED.value,
                request_id=request_id,
            )
        )
        session.commit()
        raise Rejection(409, "insufficient_funds", "Insufficient funds")

    src.balance_cents -= amount_cents
    dst.balance_cents += amount_cents
    tx = Transaction(
        src_account=src.id,
        dst_account=dst.id,
        amount_cents=amount_cents,
        status=TransactionStatus.CREATED.value,
        request_id=request_id,
    )
    session.add(tx)
    session.commit()
    return tx
