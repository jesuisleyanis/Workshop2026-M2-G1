"""Modèles SQLAlchemy 2.0 : users, accounts, transactions (schéma de la mission) + app bancaire."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum, StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TransactionStatus(str, Enum):
    CREATED = "created"
    REJECTED = "rejected"


class TransactionCategory(StrEnum):
    """Catégorie de dépense (#44). Pas un label de métrique : cardinalité figée par le contrat."""

    FOOD = "food"
    SHOPPING = "shopping"
    TRANSPORT = "transport"
    SUBSCRIPTIONS = "subscriptions"
    HEALTH = "health"
    LEISURE = "leisure"
    HOUSING = "housing"
    TRANSFER = "transfer"
    OTHER = "other"


CATEGORY_CHECK = "category IN ({})".format(", ".join(f"'{c.value}'" for c in TransactionCategory))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Habilitations du back-office (consigne additionnelle 1) : seuls operator/admin
        # accèdent au back-office durci. Garde-fou DB sur les valeurs autorisées.
        CheckConstraint("role IN ('customer', 'operator', 'admin')", name="ck_users_role_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="customer", server_default="customer"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )

    accounts: Mapped[list[Account]] = relationship(back_populates="user")
    face_enrollment: Mapped[FaceEnrollment | None] = relationship(
        back_populates="user", uselist=False
    )


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        # Garde-fou DB : un solde ne peut jamais devenir négatif, même en cas de bug applicatif.
        CheckConstraint("balance_cents >= 0", name="ck_accounts_balance_non_negative"),
        CheckConstraint(
            "monthly_limit_cents IS NULL OR monthly_limit_cents >= 0",
            name="ck_accounts_monthly_limit_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    iban_fake: Mapped[str] = mapped_column(String(34), unique=True, nullable=False)
    balance_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Plafond mensuel de virement (#46). NULL = pas de plafond : comptes de service (verify_tx,
    # trafic normal) et comptes ouverts par `auth`. Jamais de défaut implicite côté API.
    monthly_limit_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    user: Mapped[User] = relationship(back_populates="accounts")


class FaceEnrollment(Base):
    """Enrôlement biométrique d'un utilisateur (consigne additionnelle 1).

    RGPD : on ne stocke QUE l'embedding (vecteur), jamais l'image capturée. La
    reconnaissance est 1:1 (identifiant ↔ visage). Table sur le réseau `data` interne.
    """

    __tablename__ = "face_enrollments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    enrolled_by: Mapped[str] = mapped_column(String(64), nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="face_enrollment")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_transactions_amount_positive"),
        CheckConstraint(CATEGORY_CHECK, name="ck_transactions_category_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    src_account: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    dst_account: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=TransactionCategory.TRANSFER.value,
        server_default=TransactionCategory.TRANSFER.value,
    )


class Beneficiary(Base):
    """Bénéficiaire enregistré par un client (#43) : virer sans ressaisir l'IBAN.

    Pointe vers un compte existant (résolu depuis l'IBAN fictif à l'ajout). Un même compte
    n'est enregistré qu'une fois par client ; on ne s'enregistre pas soi-même (règle API).
    """

    __tablename__ = "beneficiaries"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "account_id", name="uq_beneficiaries_owner_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    iban_fake: Mapped[str] = mapped_column(String(34), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )


CARD_MAX_PAYMENT_LIMIT_CENTS = 1_000_000  # 10 000,00 EUR


class Card(Base):
    """Carte bancaire fictive (#47). JAMAIS de numéro complet (PAN) ni de CVV : `last4` seul."""

    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'frozen')", name="ck_cards_status_valid"),
        CheckConstraint("expiry_month BETWEEN 1 AND 12", name="ck_cards_expiry_month"),
        CheckConstraint(
            f"payment_limit_cents BETWEEN 0 AND {CARD_MAX_PAYMENT_LIMIT_CENTS}",
            name="ck_cards_payment_limit_bounds",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    holder: Mapped[str] = mapped_column(String(64), nullable=False)
    expiry_month: Mapped[int] = mapped_column(Integer, nullable=False)
    expiry_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, default="active", server_default="active"
    )
    payment_limit_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    contactless: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    online_payments: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )


class ScheduledTransfer(Base):
    """Virement programmé (#48), exécuté par la tâche de fond de payment-api via le ledger."""

    __tablename__ = "scheduled_transfers"
    __table_args__ = (
        CheckConstraint("frequency IN ('once', 'weekly', 'monthly')", name="ck_sched_frequency"),
        CheckConstraint(
            "status IN ('active', 'paused', 'cancelled', 'completed')", name="ck_sched_status"
        ),
        CheckConstraint("amount_cents > 0", name="ck_sched_amount_positive"),
        CheckConstraint(CATEGORY_CHECK, name="ck_sched_category_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    src_account: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    dst_account: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False, default="transfer")
    frequency: Mapped[str] = mapped_column(String(8), nullable=False)
    start_on: Mapped[date] = mapped_column(Date, nullable=False)
    # NULL quand plus rien n'est dû (annulée / terminée).
    next_run_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    end_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )


class ScheduledRun(Base):
    """Exécution d'une échéance. UNIQUE (scheduled_id, run_on) = clé d'idempotence : la ligne est
    réservée AVANT le virement, donc un redémarrage par la remédiation ou une seconde réplique ne
    peut jamais exécuter deux fois la même échéance (au plus une fois)."""

    __tablename__ = "scheduled_runs"
    __table_args__ = (
        UniqueConstraint("scheduled_id", "run_on", name="uq_scheduled_runs_once"),
        CheckConstraint(
            "status IN ('pending', 'executed', 'failed')", name="ck_scheduled_runs_status"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheduled_id: Mapped[int] = mapped_column(
        ForeignKey("scheduled_transfers.id"), nullable=False, index=True
    )
    run_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )
