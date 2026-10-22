"""Catégorie de dépense sur les transactions (app bancaire, #44).

Colonne NOT NULL avec défaut serveur `transfer` : les lignes existantes et tout client qui
n'envoie pas de catégorie (verify_tx, trafic normal historique) restent valides.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# Figé ici (et non importé des modèles) : une migration ne doit pas changer après coup.
CATEGORIES = (
    "food",
    "shopping",
    "transport",
    "subscriptions",
    "health",
    "leisure",
    "housing",
    "transfer",
    "other",
)


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(
            sa.Column("category", sa.String(16), nullable=False, server_default="transfer")
        )
        batch.create_check_constraint(
            "ck_transactions_category_valid",
            "category IN ({})".format(", ".join(f"'{c}'" for c in CATEGORIES)),
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("ck_transactions_category_valid", type_="check")
        batch.drop_column("category")
