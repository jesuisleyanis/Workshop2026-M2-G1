"""Schémas d'entrée/sortie de l'API payment."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)
from resilience_db.models import CARD_MAX_PAYMENT_LIMIT_CENTS, TransactionCategory


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
    # Bornés à l'INTEGER Postgres : au-delà, un DataError deviendrait un faux db_error (503)
    # exploitable par n'importe quel client pour déclencher la détection ML et la remédiation.
    src_account: StrictInt = Field(ge=1, le=2**31 - 1)
    dst_account: StrictInt = Field(ge=1, le=2**31 - 1)
    amount_cents: StrictInt
    # Facultatif (#44) : verify_tx et le trafic normal historique n'en envoient pas.
    category: TransactionCategory = TransactionCategory.TRANSFER


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    src_account: int
    dst_account: int
    amount_cents: int
    status: str
    created_at: datetime
    request_id: str | None
    # Catégorie choisie par l'ÉMETTEUR : masquée (None) pour le destinataire d'un virement.
    category: TransactionCategory | None


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


class CategoryShare(BaseModel):
    category: TransactionCategory
    amount_cents: int
    share: float


class DaySpending(BaseModel):
    date: date
    amount_cents: int


class SpendingOut(BaseModel):
    period: Literal["week", "month"]
    offset: int
    start: date
    end: date  # exclusif
    total_cents: int
    by_category: list[CategoryShare]
    by_day: list[DaySpending]


class LimitOut(BaseModel):
    account_id: int
    # null = pas de plafond (comptes de service : verify_tx, trafic normal)
    monthly_limit_cents: int | None
    used_cents: int
    remaining_cents: int | None
    period_end: date  # 1er du mois suivant (UTC), date de remise à zéro


class CardOut(BaseModel):
    """Jamais de numéro complet ni de CVV : ils n'existent pas côté serveur."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    last4: str
    holder: str
    expiry_month: int
    expiry_year: int
    status: Literal["active", "frozen"]
    payment_limit_cents: int
    contactless: bool
    online_payments: bool


class CardPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")  # pas de champ inattendu (ex. status, last4)

    payment_limit_cents: StrictInt | None = Field(None, ge=0, le=CARD_MAX_PAYMENT_LIMIT_CENTS)
    contactless: StrictBool | None = None
    online_payments: StrictBool | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> CardPatch:
        if not self.model_fields_set or any(
            getattr(self, f) is None for f in self.model_fields_set
        ):
            raise ValueError("at least one non-null setting is required")
        return self


class ScheduleIn(BaseModel):
    # Bornés à l'INTEGER Postgres : au-delà, un DataError deviendrait un faux db_error pour le ML.
    src_account: StrictInt = Field(ge=1, le=2**31 - 1)
    dst_account: StrictInt = Field(ge=1, le=2**31 - 1)
    amount_cents: StrictInt
    category: TransactionCategory = TransactionCategory.TRANSFER
    frequency: Literal["once", "weekly", "monthly"]
    start_on: date
    end_on: date | None = None


class ScheduleStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["paused", "active"]


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_on: date
    status: Literal["pending", "executed", "failed"]
    error_code: str | None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    src_account: int
    dst_account: int
    amount_cents: int
    category: TransactionCategory
    frequency: Literal["once", "weekly", "monthly"]
    start_on: date
    next_run_on: date | None
    end_on: date | None
    status: Literal["active", "paused", "cancelled", "completed"]
    last_run: RunOut | None = None


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None
