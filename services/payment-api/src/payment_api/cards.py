"""Cartes bancaires fictives (#47) : consultation, gel/dégel idempotents, réglages bornés.

Pas de HTTP ici : lève `Rejection`. Propriété = la carte est rattachée à un compte du client ;
sinon 404 identique à un id inconnu (anti-IDOR). Aucun PAN ni CVV n'existe dans le modèle.
"""

from __future__ import annotations

from resilience_db.models import Account, Card, User
from sqlalchemy import select
from sqlalchemy.orm import Session

from payment_api.ledger import Rejection
from payment_api.notifications import notify


def list_for(session: Session, user: User) -> list[Card]:
    return list(
        session.scalars(
            select(Card)
            .join(Account, Account.id == Card.account_id)
            .where(Account.user_id == user.id)
            .order_by(Card.id)
        )
    )


def owned(session: Session, user: User, card_id: int) -> Card:
    """Carte du client, VERROUILLÉE jusqu'au commit : un gel concurrent ne peut pas s'intercaler
    entre la lecture du statut et l'écriture des réglages (même principe que le ledger)."""
    card = session.scalar(
        select(Card)
        .join(Account, Account.id == Card.account_id)
        .where(Card.id == card_id, Account.user_id == user.id)
        .with_for_update(of=Card)
    )
    if card is None:
        raise Rejection(404, "card_not_found", "Card not found")
    return card


def set_status(session: Session, user: User, card_id: int, status: str) -> tuple[Card, bool]:
    """Renvoie (carte, changé ?) : geler une carte gelée est un succès sans effet (idempotent)."""
    card = owned(session, user, card_id)
    changed = card.status != status
    if changed:
        card.status = status
        frozen = status == "frozen"
        notify(
            session,
            user.id,
            "card_frozen" if frozen else "card_unfrozen",
            "Carte gelée" if frozen else "Carte dégelée",
            f"Carte •••• {card.last4} {'gelée' if frozen else 'de nouveau active'}.",
        )
        session.commit()
    return card, changed


def update(session: Session, user: User, card_id: int, changes: dict) -> tuple[Card, list[str]]:
    """Renvoie (carte, champs réellement modifiés) : renvoyer la valeur actuelle n'est pas un changement."""
    card = owned(session, user, card_id)
    if card.status == "frozen":
        raise Rejection(409, "card_frozen", "Unfreeze the card before changing its settings")
    changed = sorted(f for f, v in changes.items() if getattr(card, f) != v)
    for field in changed:
        setattr(card, field, changes[field])
    session.commit()
    return card, changed
