"""Notifications in-app (app bancaire, #49).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TYPES = (
    "transfer_sent",
    "transfer_received",
    "transfer_rejected",
    "limit_80",
    "card_frozen",
    "card_unfrozen",
    "scheduled_executed",
    "scheduled_failed",
)


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(24), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("body", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ({})".format(", ".join(f"'{t}'" for t in TYPES)), name="ck_notifications_type"
        ),
    )
    op.create_index("ix_notifications_user_id_id", "notifications", ["user_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_user_id_id", table_name="notifications")
    op.drop_table("notifications")
