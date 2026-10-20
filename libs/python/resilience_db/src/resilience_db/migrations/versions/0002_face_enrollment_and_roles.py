"""Habilitations + enrôlement biométrique (consigne additionnelle 1).

Ajoute `users.role` (customer|operator|admin) et la table `face_enrollments`
(embedding seul — jamais l'image, RGPD).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode : SQLite ne sait pas ALTER une contrainte en place (copy-and-move),
    # PostgreSQL applique un ALTER classique. Même migration pour les deux dialectes.
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "role",
                sa.String(16),
                nullable=False,
                server_default="customer",
            )
        )
        batch.create_check_constraint(
            "ck_users_role_valid",
            "role IN ('customer', 'operator', 'admin')",
        )
    op.create_table(
        "face_enrollments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("enrolled_by", sa.String(64), nullable=False),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_face_enrollments_user_id", "face_enrollments", ["user_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_face_enrollments_user_id", table_name="face_enrollments")
    op.drop_table("face_enrollments")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_role_valid", type_="check")
        batch.drop_column("role")
