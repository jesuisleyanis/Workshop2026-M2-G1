"""Déblocage d'une IP par l'opérateur (bouton du dashboard) : DELETE /waf/blocked-ips/{ip}."""

import pytest
from blocklist import read_deny_file, remove_ip
from conftest import OPERATOR_TOKEN, TOKEN, Env, make_settings, make_table
from fastapi.testclient import TestClient
from main import create_app

SERVICE = {"Authorization": f"Bearer {TOKEN}"}
AUTH = {"Authorization": f"Bearer {OPERATOR_TOKEN}"}  # déblocage = action opérateur


def deny(tmp_path, *ips):
    f = tmp_path / "blocked_ips.conf"
    f.write_text("\n".join(["# géré par la remédiation", *(f"{ip} 1;" for ip in ips), ""]), encoding="utf-8")
    return f


def test_remove_ip_keeps_comments_and_other_ips(tmp_path):
    f = deny(tmp_path, "192.168.137.115", "203.0.113.9")
    assert remove_ip(f, "192.168.137.115") is True
    assert read_deny_file(f) == ["203.0.113.9"]
    assert f.read_text(encoding="utf-8").startswith("# géré par la remédiation")
    assert remove_ip(f, "192.168.137.115") is False  # déjà débloquée : idempotent
    assert not (tmp_path / "blocked_ips.conf.tmp").exists()  # écriture atomique, rien ne traîne
    with pytest.raises(ValueError):
        remove_ip(f, "1.2.3.4; deny all")


@pytest.fixture
def api(tmp_path):
    env = Env(table=make_table(cooldown=0), verify=[True])
    f = deny(tmp_path, "192.168.137.115")
    app = create_app(make_settings(waf_deny_file=str(f)), table=env.engine.table, services=env.services)
    with TestClient(app) as c:
        c.env, c.deny = env, f
        yield c


def test_unblock_removes_the_ip_and_reloads_the_waf(api):
    r = api.delete("/waf/blocked-ips/192.168.137.115", headers=AUTH)
    assert r.status_code == 200 and r.json() == {"unblocked": "192.168.137.115", "waf_reloaded": 1}
    assert read_deny_file(api.deny) == []
    # rechargement à chaud du WAF (SIGHUP) via le proxy, rien d'autre
    assert ("POST", "/containers/cid-waf/kill") in api.env.net.docker_calls()


def test_unblock_errors_follow_the_contract(api):
    assert api.delete("/waf/blocked-ips/192.168.137.115").status_code == 401  # jeton obligatoire
    r = api.delete("/waf/blocked-ips/not-an-ip", headers=AUTH)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_ip"
    r = api.delete("/waf/blocked-ips/203.0.113.77", headers=AUTH)
    assert r.status_code == 404 and r.json()["error"]["code"] == "ip_not_blocked"
    assert read_deny_file(api.deny) == ["192.168.137.115"]  # rien retiré par erreur


# ------------------------------------------------------------- jeton opérateur (écriture humaine)
def test_unblock_requires_the_operator_token_not_the_service_token(api):
    path = "/waf/blocked-ips/192.168.137.115"
    assert api.delete(path).status_code == 401  # aucun jeton
    assert api.delete(path, headers={"Authorization": "Bearer " + "w" * 40}).status_code == 401
    # Jeton de SERVICE (celui qu'injecte le nginx du dashboard pour les lectures) : refusé explicitement.
    r = api.delete(path, headers=SERVICE)
    assert r.status_code == 403 and r.json()["error"]["code"] == "operator_token_required"
    assert read_deny_file(api.deny) == ["192.168.137.115"]  # rien n'a été retiré
    assert api.delete(path, headers=AUTH).status_code == 200


def test_read_routes_keep_the_service_token_only(api):
    assert api.get("/waf/blocked-ips", headers=SERVICE).status_code == 200
    assert api.get("/incidents", headers=SERVICE).status_code == 200
    # Le jeton opérateur n'ouvre pas l'API machine-à-machine (moindre privilège, aucun usage prévu).
    assert api.get("/waf/blocked-ips", headers=AUTH).status_code == 401
    assert api.post("/events", headers=AUTH, json={}).status_code == 401


@pytest.mark.parametrize("operator_token", [None, "court", TOKEN])
def test_operator_routes_fail_closed_when_operator_token_is_unusable(tmp_path, operator_token):
    # Absent, trop court ou ÉGAL au jeton de service : aucune action opérateur possible (503).
    env = Env(table=make_table(cooldown=0), verify=[True])
    f = deny(tmp_path, "192.168.137.115")
    settings = make_settings(waf_deny_file=str(f), operator_token=operator_token)
    assert settings.operator_token_configured is False
    app = create_app(settings, table=env.engine.table, services=env.services)
    with TestClient(app) as c:
        for headers in (SERVICE, {"Authorization": f"Bearer {operator_token}"}):
            r = c.delete("/waf/blocked-ips/192.168.137.115", headers=headers)
            assert r.status_code == 503 and r.json()["error"]["code"] == "auth_not_configured"
        assert c.get("/waf/blocked-ips", headers=SERVICE).status_code == 200  # lectures intactes
    assert read_deny_file(f) == ["192.168.137.115"]


def test_operator_token_is_read_from_env_or_file(tmp_path):
    from config import Settings

    secret = tmp_path / "op"
    secret.write_text(OPERATOR_TOKEN + "\n", encoding="utf-8")
    s = Settings.from_env({"REMEDIATION_TOKEN": TOKEN, "REMEDIATION_OPERATOR_TOKEN_FILE": str(secret)})
    assert s.operator_token == OPERATOR_TOKEN and s.operator_token_configured
    s = Settings.from_env({"REMEDIATION_TOKEN": TOKEN, "REMEDIATION_OPERATOR_TOKEN": OPERATOR_TOKEN})
    assert s.operator_token_configured
    assert not Settings.from_env({"REMEDIATION_TOKEN": TOKEN}).operator_token_configured
