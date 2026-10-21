"""Plafond mensuel de virement par compte (app bancaire, #46).

Colonne NULLABLE : NULL = pas de plafond. Les comptes existants (dont ceux de verify_tx et du
trafic normal) restent donc sans plafond après la migration : la démo ne peut pas régresser.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("monthly_limit_cents", sa.BigInteger(), nullable=True))
        batch.create_check_constraint(
            "ck_accounts_monthly_limit_non_negative",
            "monthly_limit_cents IS NULL OR monthly_limit_cents >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("ck_accounts_monthly_limit_non_negative", type_="check")
        batch.drop_column("monthly_limit_cents")
