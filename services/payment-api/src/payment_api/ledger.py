"""Règles métier du virement fictif. Pas de HTTP ici : lève `Rejection`, renvoie une Transaction."""

from __future__ import annotations

from datetime import UTC, datetime

from resilience_db.models import Account, Transaction, TransactionStatus, User
from sqlalchemy import select
from sqlalchemy.orm import Session

from payment_api.limits import used_cents
from payment_api.notifications import euros, notify

MAX_AMOUNT_CENTS = 100_000_000  # 1 000 000,00 EUR fictifs


class Rejection(Exception):
    """Virement refusé pour une raison métier (-> event transaction_rejected)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def check_amount_and_accounts(src_id: int, dst_id: int, amount_cents: int) -> None:
    """Règles statiques d'un virement, partagées avec les virements programmés (#48)."""
    if amount_cents <= 0:
        raise Rejection(422, "invalid_amount", "Amount must be strictly positive")
    if amount_cents > MAX_AMOUNT_CENTS:
        raise Rejection(422, "amount_too_large", "Amount exceeds the maximum allowed")
    if src_id == dst_id:
        raise Rejection(422, "same_account", "Source and destination must differ")


def transfer(
    session: Session,
    user: User,
    src_id: int,
    dst_id: int,
    amount_cents: int,
    request_id: str | None,
    category: str = "transfer",
    now: datetime | None = None,
    notify_sender: bool = True,
) -> Transaction:
    """Débite `src_id` (qui doit appartenir à `user`) et crédite `dst_id`, atomiquement.

    Notifications (#49) écrites dans la même transaction. `notify_sender=False` : l'appelant
    (exécuteur des virements programmés) notifie l'émetteur lui-même.
    """
    check_amount_and_accounts(src_id, dst_id, amount_cents)

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

    def reject(status: int, code: str, message: str) -> Rejection:
        # Tentative traçable : on persiste la transaction refusée (R2), sans toucher aux soldes.
        session.add(
            Transaction(
                src_account=src.id,
                dst_account=dst.id,
                amount_cents=amount_cents,
                status=TransactionStatus.REJECTED.value,
                request_id=request_id,
                category=category,
            )
        )
        if notify_sender:
            reason = "plafond mensuel atteint" if code == "limit_exceeded" else "solde insuffisant"
            notify(
                session,
                src.user_id,
                "transfer_rejected",
                "Virement refusé",
                f"{euros(amount_cents)} vers le compte n°{dst.id} : {reason}.",
            )
        session.commit()
        return Rejection(status, code, message)

    # Plafond mensuel (#46), contrôlé sous le verrou de la source : deux virements concurrents
    # ne peuvent pas le dépasser ensemble. Sans plafond (NULL) ou entre ses propres comptes :
    # aucun calcul (pas de requête ajoutée sur les comptes de service à fort trafic).
    limit = src.monthly_limit_cents
    capped = limit is not None and dst.user_id != src.user_id
    used = used_cents(session, src, now or datetime.now(UTC)) if capped else 0
    if capped and used + amount_cents > limit:
        raise reject(409, "limit_exceeded", "Monthly transfer limit exceeded")

    if src.balance_cents < amount_cents:
        raise reject(409, "insufficient_funds", "Insufficient funds")

    src.balance_cents -= amount_cents
    dst.balance_cents += amount_cents
    tx = Transaction(
        src_account=src.id,
        dst_account=dst.id,
        amount_cents=amount_cents,
        status=TransactionStatus.CREATED.value,
        request_id=request_id,
        category=category,
    )
    session.add(tx)
    if dst.user_id != src.user_id:  # virement interne : pas de notification
        if notify_sender:
            notify(
                session,
                src.user_id,
                "transfer_sent",
                "Virement émis",
                f"{euros(amount_cents)} vers le compte n°{dst.id}.",
            )
        notify(
            session,
            dst.user_id,
            "transfer_received",
            "Virement reçu",
            f"{euros(amount_cents)} du compte n°{src.id}.",
        )
        # Plafond franchissant 80 % : une seule alerte au passage du seuil.
        if capped and used < 0.8 * limit <= used + amount_cents:
            notify(
                session,
                src.user_id,
                "limit_80",
                "Plafond bientôt atteint",
                f"80 % du plafond mensuel du compte n°{src.id} utilisés"
                f" (reste {euros(limit - used - amount_cents)}).",
            )
    session.commit()
    return tx
