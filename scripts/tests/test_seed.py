"""scripts/seed.py : un seul chemin de seed (resilience_db.seed), comptes financés, idempotent."""
from __future__ import annotations

import pytest

pytest.importorskip("resilience_db")

import seed  # noqa: E402  (scripts/ est dans sys.path via conftest)
from resilience_db.config import make_engine, make_session_factory  # noqa: E402
from resilience_db.models import Beneficiary, User  # noqa: E402
from resilience_db.seed import PAYEES  # noqa: E402
from sqlalchemy import select  # noqa: E402


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'seed.sqlite3'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SEED_PASSWORD", "fake-seed-pass")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    return url


def test_seed_direct_funds_accounts_and_is_idempotent(db_env, capsys):
    assert seed.main() == 0
    assert "5 utilisateur(s)" in capsys.readouterr().out
    assert seed.main() == 0  # rejouable sans doublon
    with make_session_factory(make_engine(db_env))() as s:
        users = s.scalars(select(User).where(User.username.like("demo%")).order_by(User.username)).all()
        accounts = [a for u in users for a in u.accounts]
        beneficiaries = s.scalars(select(Beneficiary)).all()
        payees = s.scalars(select(User).where(User.username.like("tiers%"))).all()
    assert [u.username for u in users] == ["demo01", "demo02", "demo03", "demo04", "demo05"]
    assert len(accounts) == 5
    assert all(a.balance_cents == 100_000 and a.currency == "EUR" for a in accounts), "comptes financés"
    assert len(payees) == len(PAYEES), "tiers fictifs destinataires (#43)"
    assert len(beneficiaries) == 5 * 8, "8 bénéficiaires par client de démo, sans doublon au 2e passage"


def test_without_db_config_delegates_to_compose(monkeypatch):
    for var in ("DATABASE_URL", "POSTGRES_PASSWORD", "POSTGRES_PASSWORD_FILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SEED_PASSWORD", "fake-seed-pass")
    calls = []

    class _Done:
        returncode = 0

    monkeypatch.setattr(seed.subprocess, "run", lambda cmd, env=None: calls.append((cmd, env)) or _Done())
    assert seed.main() == 0
    cmd, env = calls[0]
    assert cmd[:3] == ["docker", "compose", "-f"] and cmd[-3:] == ["python", "-m", "resilience_db.seed"]
    assert "SEED_MONTHLY_LIMIT_CENTS" in cmd and env["SEED_MONTHLY_LIMIT_CENTS"] == "80000", "#46 transmis"
    assert "payment-api" in cmd and env["SEED_PASSWORD"] == "fake-seed-pass"


@pytest.mark.parametrize("present", [True, False])
def test_compose_path_passes_the_root_env_file_when_present(monkeypatch, tmp_path, present):
    # Sans --env-file, Compose ne lit pas le .env de la racine et échoue sur les ${VAR:?}.
    for var in ("DATABASE_URL", "POSTGRES_PASSWORD", "POSTGRES_PASSWORD_FILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SEED_PASSWORD", "fake-seed-pass")
    env_file = tmp_path / ".env"
    if present:
        env_file.write_text("SEED_PASSWORD=x\n", encoding="utf-8")
    monkeypatch.setattr(seed, "ENV_FILE", env_file)
    calls = []

    class _Done:
        returncode = 0

    monkeypatch.setattr(seed.subprocess, "run", lambda cmd, env=None: calls.append(cmd) or _Done())
    assert seed.main() == 0
    cmd = calls[0]
    if present:
        i = cmd.index("--env-file")
        assert cmd[i + 1] == str(env_file) and i < cmd.index("exec")
    else:
        assert "--env-file" not in cmd


def test_compose_path_requires_seed_password(monkeypatch, capsys):
    for var in ("DATABASE_URL", "POSTGRES_PASSWORD", "POSTGRES_PASSWORD_FILE", "SEED_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    assert seed.main() == 1
    assert "SEED_PASSWORD" in capsys.readouterr().err
