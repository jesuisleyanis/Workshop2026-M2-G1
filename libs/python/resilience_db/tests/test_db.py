"""Tests du module partagé : migrations == modèles, seed idempotent, config sans secret en dur."""

import pytest
from resilience_db import Base, build_database_url, make_engine, make_session_factory
from resilience_db.migrate import upgrade
from resilience_db.models import Account, FaceEnrollment, User
from resilience_db.passwords import hash_password, verify_password
from resilience_db.seed import seed_demo_data
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError


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


def test_seed_reset_passwords_realigns_existing_accounts_after_rotation():
    # Rotation de SEED_PASSWORD : sans reset, les comptes existants gardent l'ancien mot de passe
    # (verify_tx et la remédiation échouent au login) ; avec reset, ils sont réalignés, soldes intacts.
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        seed_demo_data(s, "ancien", users=2)
        s.query(Account).filter_by(id=1).one().balance_cents = 4242
        s.commit()
        assert seed_demo_data(s, "nouveau", users=2) == []
        assert verify_password("ancien", s.query(User).filter_by(username="demo01").one().password_hash)
        assert seed_demo_data(s, "nouveau", users=3, reset_passwords=True) == ["demo03"]
        for user in s.query(User).all():
            assert verify_password("nouveau", user.password_hash)
        assert s.query(Account).filter_by(id=1).one().balance_cents == 4242


def test_user_role_defaults_to_customer_and_rejects_unknown_role():
    # Habilitations (consigne add. 1) : rôle par défaut `customer`, valeurs bornées en DB.
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        u = User(username="op01", password_hash=hash_password("s3cret-pass"))
        s.add(u)
        s.commit()
        assert u.role == "customer"
        u.role = "operator"
        s.commit()
        assert s.query(User).filter_by(username="op01").one().role == "operator"
        s.add(User(username="bad", password_hash="x", role="root"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_face_enrollment_stores_embedding_one_per_user():
    # RGPD : on stocke l'embedding (vecteur), jamais l'image ; un seul enrôlement par user.
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        u = User(username="op01", password_hash=hash_password("s3cret-pass"))
        s.add(u)
        s.commit()
        s.add(
            FaceEnrollment(
                user_id=u.id,
                embedding=b"\x00\x01\x02vector-bytes",
                model_version="buffalo_s-1.0",
                enrolled_by="admin01",
            )
        )
        s.commit()
        enr = s.query(FaceEnrollment).filter_by(user_id=u.id).one()
        assert enr.embedding == b"\x00\x01\x02vector-bytes"
        assert enr.model_version == "buffalo_s-1.0"
        # Un second enrôlement pour le même utilisateur est refusé (contrainte d'unicité).
        s.add(
            FaceEnrollment(
                user_id=u.id,
                embedding=b"other",
                model_version="buffalo_s-1.0",
                enrolled_by="admin01",
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


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
