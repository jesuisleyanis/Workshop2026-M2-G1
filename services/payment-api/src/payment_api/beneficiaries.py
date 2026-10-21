"""Règles métier des bénéficiaires (#43). Pas de HTTP ici : lève `Rejection`."""

from __future__ import annotations

from resilience_db.models import Account, Beneficiary, User
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from payment_api.ledger import Rejection

MAX_BENEFICIARIES = 100  # par client : borne la croissance de la table (abus, scripts)


def normalize_iban(raw: str) -> str:
    return "".join(raw.split()).upper()


def list_for(session: Session, user: User) -> list[Beneficiary]:
    return list(
        session.scalars(
            select(Beneficiary)
            .where(Beneficiary.owner_user_id == user.id)
            .order_by(Beneficiary.display_name, Beneficiary.id)
        )
    )


def add(session: Session, user: User, display_name: str, iban_fake: str) -> Beneficiary:
    iban = normalize_iban(iban_fake)
    account = session.scalar(
        select(Account).where(func.upper(func.replace(Account.iban_fake, " ", "")) == iban)
    )
    if account is None:
        raise Rejection(404, "account_not_found", "No account matches this IBAN")
    if account.user_id == user.id:
        raise Rejection(422, "own_account", "You cannot add your own account as a beneficiary")
    count = session.scalar(
        select(func.count(Beneficiary.id)).where(Beneficiary.owner_user_id == user.id)
    )
    if count >= MAX_BENEFICIARIES:
        raise Rejection(409, "beneficiary_limit", "Too many beneficiaries")
    beneficiary = Beneficiary(
        owner_user_id=user.id,
        display_name=display_name,
        account_id=account.id,
        iban_fake=account.iban_fake,
    )
    session.add(beneficiary)
    try:
        session.commit()
    except IntegrityError:  # (owner, account) déjà présent, y compris en course concurrente
        session.rollback()
        raise Rejection(409, "beneficiary_exists", "This beneficiary is already registered")
    return beneficiary


def remove(session: Session, user: User, beneficiary_id: int) -> None:
    beneficiary = session.get(Beneficiary, beneficiary_id)
    # Bénéficiaire d'autrui : même réponse qu'un id inconnu (pas d'oracle d'existence).
    if beneficiary is None or beneficiary.owner_user_id != user.id:
        raise Rejection(404, "beneficiary_not_found", "Beneficiary not found")
    session.delete(beneficiary)
    session.commit()
