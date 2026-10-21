"""Tests du module partagé : migrations == modèles, seed idempotent, config sans secret en dur."""

from datetime import UTC, datetime, timedelta

import pytest
from resilience_db import Base, build_database_url, make_engine, make_session_factory
from resilience_db.migrate import upgrade
from resilience_db.models import (
    Account,
    Beneficiary,
    Card,
    FaceEnrollment,
    Transaction,
    TransactionCategory,
    User,
)
from resilience_db.passwords import hash_password, verify_password
from resilience_db.seed import HISTORY, PAYEES, demo_iban, payee_iban, seed_demo_data
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def test_migration_creates_same_schema_as_models(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/m.db")
    upgrade(engine)
    insp = inspect(engine)
    assert set(Base.metadata.tables) <= set(insp.get_table_names())
    for name, table in Base.metadata.tables.items():
        assert {c["name"] for c in insp.get_columns(name)} == {c.name for c in table.columns}


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
        assert s.query(Account).count() == 3 + len(PAYEES)


def test_seed_registers_5_to_8_beneficiaries_per_demo_client_idempotently():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        seed_demo_data(s, "s3cret-pass", users=5)
        seed_demo_data(s, "s3cret-pass", users=5)  # rejouable sans doublon
        for n in range(1, 6):
            owner = s.query(User).filter_by(username=f"demo{n:02d}").one()
            rows = s.query(Beneficiary).filter_by(owner_user_id=owner.id).all()
            assert 5 <= len(rows) <= 8
            assert owner.accounts[0].id not in {b.account_id for b in rows}, "jamais soi-même"
        # Les tiers fictifs ne sont pas connectables avec le mot de passe de démo.
        payee = s.query(User).filter_by(username=PAYEES[0][0]).one()
        assert not verify_password("s3cret-pass", payee.password_hash)


def test_beneficiary_is_unique_per_owner_and_account():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        seed_demo_data(s, "s3cret-pass", users=2)
        b = s.query(Beneficiary).first()
        s.add(
            Beneficiary(
                owner_user_id=b.owner_user_id,
                display_name="dup",
                account_id=b.account_id,
                iban_fake=b.iban_fake,
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


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
    assert url.password == "p@ss/word"  # caractères spéciaux correctement encodés par URL.create


def test_password_from_file(monkeypatch, tmp_path):
    f = tmp_path / "pg"
    f.write_text("from-file\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(f))
    assert build_database_url().password == "from-file"


def test_payee_ibans_never_collide_with_demo_ibans():
    demo = {demo_iban(n) for n in range(1, 10_000)}
    assert not demo & {payee_iban(i) for i in range(1, len(PAYEES) + 1)}


def test_transaction_category_defaults_to_transfer_and_is_bounded(tmp_path):
    # Via la migration (pas create_all) : défaut serveur + CHECK réellement posés en base.
    engine = make_engine(f"sqlite:///{tmp_path}/m.db")
    upgrade(engine)
    with make_session_factory(engine)() as s:
        seed_demo_data(s, "s3cret-pass", users=2)
        a, b = s.query(Account).order_by(Account.id).limit(2).all()
        tx = Transaction(src_account=a.id, dst_account=b.id, amount_cents=1, status="created")
        s.add(tx)
        s.commit()
        assert tx.category == "transfer"
        s.execute(
            text(
                "INSERT INTO transactions (src_account, dst_account, amount_cents, status) "
                "VALUES (:a, :b, 1, 'created')"
            ),
            {"a": a.id, "b": b.id},
        )
        s.commit()
        assert s.execute(text("SELECT category FROM transactions ORDER BY id DESC")).scalar() == (
            "transfer"
        ), "défaut serveur : un INSERT sans catégorie reste valide"
        s.add(
            Transaction(
                src_account=a.id, dst_account=b.id, amount_cents=1, status="created", category="x"
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()
    from importlib import import_module

    mig = import_module("resilience_db.migrations.versions.0004_transaction_category")
    assert set(mig.CATEGORIES) == {c.value for c in TransactionCategory}, "migration = modèle"


def test_seed_history_is_categorised_and_only_for_new_clients():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        seed_demo_data(s, "s3cret-pass", users=2)
        assert s.query(Transaction).count() == 2 * len(HISTORY)
        seed_demo_data(s, "s3cret-pass", users=3)  # demo03 nouveau, demo01/02 déjà servis ce mois
        assert s.query(Transaction).count() == 3 * len(HISTORY)
        cats = {t.category for t in s.query(Transaction)}
        assert len(cats) >= 6 and cats <= {c.value for c in TransactionCategory}
        demo = s.query(User).filter_by(username="demo01").one()
        assert demo.accounts[0].balance_cents == 100_000, "solde de démo inchangé (verify_tx)"


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 11, 1, 0, 30, tzinfo=UTC),  # dimanche 1er, juste après minuit
        datetime(2026, 10, 19, 9, 0, tzinfo=UTC),  # lundi
        datetime(2026, 10, 31, 22, 0, tzinfo=UTC),
    ],
)
def test_seed_history_always_lands_in_current_week_and_month(now):
    from resilience_db.seed import WEEK_ENTRIES, seed_history

    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        seed_demo_data(s, "s3cret-pass", users=1)
        s.query(Transaction).delete()
        s.commit()
        assert seed_history(s, ["demo01"], now=now) == len(HISTORY)
        assert seed_history(s, ["demo01"], now=now) == 0, "idempotent dans le mois"
        dates = [
            t.created_at.replace(tzinfo=UTC) for t in s.query(Transaction).order_by(Transaction.id)
        ]
    month_start = now.replace(day=1, hour=0, minute=0)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0)
    assert all(month_start <= d <= now for d in dates)
    assert all(d >= week_start for d in dates[:WEEK_ENTRIES])


def test_service_accounts_are_never_capped_and_demo_clients_are():
    # #46 : demo01/demo02 portent verify_tx et le trafic normal (~1 virement/s) : un plafond les
    # ferait passer en 409, fausserait la baseline ML et ferait échouer la reprise.
    from resilience_db.seed import DEFAULT_MONTHLY_LIMIT_CENTS, SERVICE_USERS

    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        seed_demo_data(s, "s3cret-pass", users=4)
        limits = {
            u.username: u.accounts[0].monthly_limit_cents for u in s.query(User) if u.accounts
        }
    assert {"demo01", "demo02"} == set(SERVICE_USERS)
    assert limits["demo01"] is None and limits["demo02"] is None
    assert limits["demo03"] == limits["demo04"] == DEFAULT_MONTHLY_LIMIT_CENTS
    assert all(limits[f"tiers0{i}"] is None for i in range(1, 5))


def test_seed_backfills_the_limit_of_demo_clients_seeded_before_46():
    from resilience_db.seed import DEFAULT_MONTHLY_LIMIT_CENTS

    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        seed_demo_data(s, "s3cret-pass", users=3)
        for u in s.query(User):
            for a in u.accounts:
                a.monthly_limit_cents = None  # état juste après la migration 0005
        s.query(User).filter_by(username="demo03").one().accounts[0].monthly_limit_cents = None
        s.commit()
        seed_demo_data(s, "s3cret-pass", users=3)
        by = {u.username: u.accounts[0].monthly_limit_cents for u in s.query(User) if u.accounts}
    assert by["demo03"] == DEFAULT_MONTHLY_LIMIT_CENTS
    assert by["demo01"] is None and by["demo02"] is None, "service : jamais rétro-plafonnés"
    assert DEFAULT_MONTHLY_LIMIT_CENTS < 100_000, "plafond sous le solde de démo"


def test_monthly_limit_cannot_be_negative():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        u = User(username="x", password_hash="x")
        u.accounts.append(Account(iban_fake="FR76 X", balance_cents=0, monthly_limit_cents=-1))
        s.add(u)
        with pytest.raises(IntegrityError):
            s.commit()


def test_one_card_per_demo_account_without_pan_and_idempotent():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        seed_demo_data(s, "s3cret-pass", users=3)
        seed_demo_data(s, "s3cret-pass", users=3)
        cards = s.query(Card).all()
        assert len(cards) == 3
        assert all(len(c.last4) == 4 and c.last4.isdigit() and c.status == "active" for c in cards)
    assert {c.name for c in Card.__table__.columns}.isdisjoint({"pan", "number", "cvv", "cvc"})


def test_card_bounds_are_enforced_in_database(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/m.db")
    upgrade(engine)
    with make_session_factory(engine)() as s:
        seed_demo_data(s, "s3cret-pass", users=1)
        card = s.query(Card).one()
        card.payment_limit_cents = 1_000_001
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        card = s.query(Card).one()
        card.status = "stolen"
        with pytest.raises(IntegrityError):
            s.commit()
