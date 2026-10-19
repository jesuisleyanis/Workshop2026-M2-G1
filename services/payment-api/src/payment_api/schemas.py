"""Schémas d'entrée/sortie de l'API payment."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, StrictInt


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    iban_fake: str
    balance_cents: int
    currency: str


class TransactionIn(BaseModel):
    # StrictInt : pas de float ni de bool déguisé ; les montants sont des entiers en centimes.
    # Les bornes métier (montant > 0, ...) sont vérifiées dans le ledger afin d'être
    # tracées (event transaction_rejected + métrique) plutôt que rejetées en 422 muet.
    src_account: StrictInt
    dst_account: StrictInt
    amount_cents: StrictInt


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    src_account: int
    dst_account: int
    amount_cents: int
    status: str
    created_at: datetime
    request_id: str | None
