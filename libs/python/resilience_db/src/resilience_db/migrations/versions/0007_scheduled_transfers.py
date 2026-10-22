"""Virements programmés + exécutions idempotentes (app bancaire, #48).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

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
    op.create_table(
        "scheduled_transfers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("src_account", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("dst_account", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("frequency", sa.String(8), nullable=False),
        sa.Column("start_on", sa.Date(), nullable=False),
        sa.Column("next_run_on", sa.Date(), nullable=True),
        sa.Column("end_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("frequency IN ('once', 'weekly', 'monthly')", name="ck_sched_frequency"),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'cancelled', 'completed')", name="ck_sched_status"
        ),
        sa.CheckConstraint("amount_cents > 0", name="ck_sched_amount_positive"),
        sa.CheckConstraint(
            "category IN ({})".format(", ".join(f"'{c}'" for c in CATEGORIES)),
            name="ck_sched_category_valid",
        ),
    )
    op.create_index(
        "ix_scheduled_transfers_owner_user_id", "scheduled_transfers", ["owner_user_id"]
    )
    op.create_index("ix_scheduled_transfers_next_run_on", "scheduled_transfers", ["next_run_on"])
    op.create_table(
        "scheduled_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scheduled_id", sa.Integer(), sa.ForeignKey("scheduled_transfers.id"), nullable=False
        ),
        sa.Column("run_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("scheduled_id", "run_on", name="uq_scheduled_runs_once"),
        sa.CheckConstraint(
            "status IN ('pending', 'executed', 'failed')", name="ck_scheduled_runs_status"
        ),
    )
    op.create_index("ix_scheduled_runs_scheduled_id", "scheduled_runs", ["scheduled_id"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_runs_scheduled_id", table_name="scheduled_runs")
    op.drop_table("scheduled_runs")
    op.drop_index("ix_scheduled_transfers_next_run_on", table_name="scheduled_transfers")
    op.drop_index("ix_scheduled_transfers_owner_user_id", table_name="scheduled_transfers")
    op.drop_table("scheduled_transfers")
