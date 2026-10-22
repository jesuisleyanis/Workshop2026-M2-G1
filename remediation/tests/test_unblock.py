"""Déblocage d'une IP par l'opérateur (bouton du dashboard) : DELETE /waf/blocked-ips/{ip}."""

import pytest
from conftest import TOKEN, Env, make_settings, make_table
from fastapi.testclient import TestClient

from blocklist import read_deny_file, remove_ip
from main import create_app

AUTH = {"Authorization": f"Bearer {TOKEN}"}


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
