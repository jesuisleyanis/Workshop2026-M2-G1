"""Tests du module partagé : migrations == modèles, seed idempotent, config sans secret en dur."""

import pytest
from resilience_db import Base, build_database_url, make_engine, make_session_factory
from resilience_db.migrate import upgrade
from resilience_db.models import Account, User
from resilience_db.passwords import hash_password, verify_password
from resilience_db.seed import seed_demo_data
from sqlalchemy import inspect


def test_migration_creates_same_schema_as_models(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/m.db")
    upgrade(engine)
    insp = inspect(engine)
    assert set(Base.metadata.tables) <= set(insp.get_table_names())
    for name, table in Base.metadata.tables.items():
        assert {c["name"] for c in insp.get_columns(name)} == {
            c.name for c in table.columns
        }


def test_migration_is_idempotent(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/m.db")
    upgrade(engine)
    upgrade(engine)  # deuxième démarrage de service : no-op


def test_seed_is_idempotent_and_hashes_password():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        assert seed_demo_data(s, "s3cret-pass", users=3) == [
            "demo01",
            "demo02",
            "demo03",
        ]
        assert seed_demo_data(s, "s3cret-pass", users=3) == []
        user = s.query(User).filter_by(username="demo01").one()
        assert user.password_hash != "s3cret-pass"
        assert verify_password("s3cret-pass", user.password_hash)
        assert s.query(Account).count() == 3


def test_password_over_72_bytes_rejected():
    with pytest.raises(ValueError):
        hash_password("x" * 73)
    assert verify_password("x" * 73, hash_password("x" * 10)) is False


def test_postgres_url_defaults_and_no_hardcoded_password(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD_FILE", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with pytest.raises(RuntimeError):
        build_database_url()
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss/word")
    url = build_database_url()
    assert (url.host, url.port, url.database, url.username) == (
        "postgres",
        5432,
        "resilience",
        "resilience",
    )
    assert (
        url.password == "p@ss/word"
    )  # caractères spéciaux correctement encodés par URL.create


def test_password_from_file(monkeypatch, tmp_path):
    f = tmp_path / "pg"
    f.write_text("from-file\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(f))
    assert build_database_url().password == "from-file"
