"""Schéma initial : users, accounts, transactions.

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("iban_fake", sa.String(34), nullable=False, unique=True),
        sa.Column("balance_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.CheckConstraint("balance_cents >= 0", name="ck_accounts_balance_non_negative"),
    )
    op.create_index("ix_accounts_user_id", "accounts", ["user_id"])
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("src_account", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("dst_account", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.CheckConstraint("amount_cents > 0", name="ck_transactions_amount_positive"),
    )
    op.create_index("ix_transactions_src_account", "transactions", ["src_account"])
    op.create_index("ix_transactions_dst_account", "transactions", ["dst_account"])


def downgrade() -> None:
    op.drop_table("transactions")
    op.drop_table("accounts")
    op.drop_table("users")
