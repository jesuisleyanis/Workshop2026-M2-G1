"""Bénéficiaires des clients (app bancaire, #43).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "beneficiaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("iban_fake", sa.String(34), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("owner_user_id", "account_id", name="uq_beneficiaries_owner_account"),
    )
    op.create_index("ix_beneficiaries_owner_user_id", "beneficiaries", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_beneficiaries_owner_user_id", table_name="beneficiaries")
    op.drop_table("beneficiaries")
