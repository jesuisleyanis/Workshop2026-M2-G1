"""Schémas d'entrée/sortie de l'API payment."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


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


class ServiceStatusOut(BaseModel):
    # Volontairement minimal (route publique) : ni version, ni hôte, ni message d'exception.
    status: Literal["ok", "degraded"]
    checked_at: str


class BeneficiaryIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)
    # IBAN fictif tel qu'affiché (espaces tolérés) ; résolu vers un compte existant.
    iban_fake: str = Field(min_length=4, max_length=42)

    @field_validator("display_name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v or any(not c.isprintable() for c in v):
            raise ValueError("invalid display name")
        return v


class BeneficiaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    account_id: int
    iban_fake: str
    created_at: datetime
