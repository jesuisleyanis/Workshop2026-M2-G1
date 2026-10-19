"""Application des migrations Alembic, sûre en démarrage concurrent.

auth et payment-api appellent `upgrade()` au démarrage : sous PostgreSQL un verrou
consultatif sérialise les deux conteneurs ; la seconde exécution est un no-op.

    python -m resilience_db.migrate        # CLI : upgrade head
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

_LOCK_ID = 727_274_001  # arbitraire, identique pour tous les services
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return cfg


def upgrade(engine: Engine, revision: str = "head") -> None:
    with engine.connect() as conn:
        is_pg = engine.dialect.name == "postgresql"
        if is_pg:
            conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": _LOCK_ID})
            conn.commit()
        try:
            cfg = _config()
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, revision)
            conn.commit()
        finally:
            if is_pg:
                conn.rollback()
                conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": _LOCK_ID})
                conn.commit()


def main() -> int:
    from resilience_db.config import make_engine

    upgrade(make_engine())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
