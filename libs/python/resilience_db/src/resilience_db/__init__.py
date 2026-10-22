"""Schéma de base de données partagé RESILIENCE-ALPHA.

`auth` et `payment-api` sont déployés séparément mais partagent le même schéma
PostgreSQL (users, accounts, transactions). Ce paquet est l'unique source de vérité
des modèles, de la configuration de connexion et des migrations Alembic.
"""

from resilience_db.config import (
    build_database_url,
    make_engine,
    make_session_factory,
    read_secret,
)
from resilience_db.models import (
    Account,
    Base,
    Beneficiary,
    Card,
    FaceEnrollment,
    Notification,
    ScheduledRun,
    ScheduledTransfer,
    Transaction,
    TransactionCategory,
    TransactionStatus,
    User,
)

__all__ = [
    "Account",
    "Base",
    "Beneficiary",
    "Card",
    "FaceEnrollment",
    "Notification",
    "ScheduledRun",
    "ScheduledTransfer",
    "Transaction",
    "TransactionCategory",
    "TransactionStatus",
    "User",
    "build_database_url",
    "make_engine",
    "make_session_factory",
    "read_secret",
]
