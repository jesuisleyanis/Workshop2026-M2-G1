"""Cartes bancaires fictives (app bancaire, #47). Jamais de PAN ni de CVV : `last4` seul.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

MAX_PAYMENT_LIMIT_CENTS = 1_000_000  # figé ici : une migration ne change pas après coup


def upgrade() -> None:
    op.create_table(
        "cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        sa.Column("holder", sa.String(64), nullable=False),
        sa.Column("expiry_month", sa.Integer(), nullable=False),
        sa.Column("expiry_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="active"),
        sa.Column("payment_limit_cents", sa.BigInteger(), nullable=False),
        sa.Column("contactless", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("online_payments", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("status IN ('active', 'frozen')", name="ck_cards_status_valid"),
        sa.CheckConstraint("expiry_month BETWEEN 1 AND 12", name="ck_cards_expiry_month"),
        sa.CheckConstraint(
            f"payment_limit_cents BETWEEN 0 AND {MAX_PAYMENT_LIMIT_CENTS}",
            name="ck_cards_payment_limit_bounds",
        ),
    )
    op.create_index("ix_cards_account_id", "cards", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_cards_account_id", table_name="cards")
    op.drop_table("cards")
