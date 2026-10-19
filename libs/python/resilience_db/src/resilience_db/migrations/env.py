"""Environnement Alembic : connexion fournie par resilience_db.migrate, ou URL de l'env (CLI)."""

from alembic import context

from resilience_db.config import make_engine
from resilience_db.models import Base

target_metadata = Base.metadata


def run_migrations() -> None:
    connection = context.config.attributes.get("connection")
    if connection is None:  # usage CLI `alembic upgrade head`
        with make_engine().connect() as conn:
            _run(conn)
            conn.commit()
    else:
        _run(connection)


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
