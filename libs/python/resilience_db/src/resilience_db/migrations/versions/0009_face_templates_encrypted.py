"""Enrôlement biométrique multi-poses : photos scellées + poses enrôlées.

Ajoute `face_enrollments.photos` (blob scellé AES-GCM, nullable) et `face_enrollments.poses`
(« face,gauche,droite »). La colonne `embedding` contient désormais un blob scellé des
gabarits par pose (le chiffrement est applicatif, côté face-id).

Numérotée 0003 sur la branche face-auth, renumérotée 0009 à la fusion avec `main` (dont les
migrations 0003-0008 occupaient déjà la chaîne) : une seule tête Alembic.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode : même migration pour SQLite (copy-and-move) et PostgreSQL (ALTER classique).
    with op.batch_alter_table("face_enrollments") as batch:
        batch.add_column(sa.Column("photos", sa.LargeBinary(), nullable=True))
        batch.add_column(
            sa.Column("poses", sa.String(64), nullable=False, server_default="face")
        )


def downgrade() -> None:
    with op.batch_alter_table("face_enrollments") as batch:
        batch.drop_column("poses")
        batch.drop_column("photos")
