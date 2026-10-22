"""Durée de vie des blocages WAF (REMEDIATION_WAF_BLOCK_TTL_S) : échéance écrite, purge, rechargement."""

from __future__ import annotations

import logging
import time

import httpx
import pytest
from actions import build_action
from actions.base import ActionContext
from actions.docker_proxy import DockerProxy
from actions.waf import purge_and_reload
from blocklist import list_blocked_ips, purge_expired, read_deny_entries, read_deny_file
from config import Settings
from conftest import TOKEN, Env, FakeNetwork, FakeRunner, make_event, make_settings, make_table
from fastapi.testclient import TestClient
from main import create_app

AUTH = {"Authorization": f"Bearer {TOKEN}"}
NOW = 1_800_000_000
LOG = logging.getLogger("remediation-test")


def deny(tmp_path, *lines: str):
    f = tmp_path / "blocked_ips.conf"
    f.write_text("\n".join(["# géré par la remédiation", *lines, ""]), encoding="utf-8")
    return f


def test_settings_ttl_default_env_and_validation():
    assert Settings().waf_block_ttl_s == 3600  # défaut : un faux positif ne bannit pas indéfiniment
    assert Settings.from_env({"REMEDIATION_WAF_BLOCK_TTL_S": "0"}).waf_block_ttl_s == 0  # 0 = permanent
    assert Settings.from_env({"REMEDIATION_WAF_BLOCK_TTL_S": "120"}).waf_block_ttl_s == 120
    with pytest.raises(ValueError, match="TTL"):
        Settings(waf_block_ttl_s=-1)


def test_purge_removes_only_expired_lines_and_keeps_legacy_permanent_entries(tmp_path):
    f = deny(tmp_path,
             "198.51.100.1 1;",                              # ancien format : permanente
             f"198.51.100.2 1; # until={NOW - 1}",            # échue
             f"198.51.100.3 1; # until={NOW + 60}",           # encore valide
             f"::ffff:198.51.100.4 1; # until={NOW}")         # échéance atteinte = échue
    assert read_deny_entries(f) == [("198.51.100.1", None), ("198.51.100.2", NOW - 1),
                                    ("198.51.100.3", NOW + 60), ("198.51.100.4", NOW)]
    assert purge_expired(f, NOW) == ["198.51.100.2", "198.51.100.4"]
    assert read_deny_file(f) == ["198.51.100.1", "198.51.100.3"]
    assert f.read_text(encoding="utf-8").startswith("# géré par la remédiation")  # commentaires conservés
    assert not (tmp_path / "blocked_ips.conf.tmp").exists()  # écriture atomique, rien ne traîne
    mtime = f.stat().st_mtime_ns
    assert purge_expired(f, NOW) == [] and f.stat().st_mtime_ns == mtime  # rien d'échu : aucune écriture
    assert purge_expired(tmp_path / "absent.conf", NOW) == []


def test_blocked_ips_expose_the_expiry_or_none_when_permanent(tmp_path):
    f = deny(tmp_path, "198.51.100.1 1;", "198.51.100.3 1; # until=1800000060")
    out = {e["ip"]: e["expires_at"] for e in list_blocked_ips(f, [])}
    assert out == {"198.51.100.1": None, "198.51.100.3": "2027-01-15T08:01:00Z"}


def _ctx(net: FakeNetwork, settings: Settings, changed: bool | None = True) -> ActionContext:
    http = httpx.AsyncClient(transport=httpx.MockTransport(net.handler))
    runner = FakeRunner(changed=changed)
    return ActionContext(settings=settings, http=http, docker=DockerProxy(http, settings.docker_proxy_url),
                         runner=runner, log=LOG, event=make_event(source_ip="203.0.113.9"), incident_id="inc-1")


@pytest.mark.anyio
async def test_block_writes_an_expiry_and_ttl_zero_means_permanent(tmp_path):
    f = deny(tmp_path)
    ctx = _ctx(FakeNetwork(), make_settings(waf_deny_file=str(f), waf_block_ttl_s=600))
    before = int(time.time())
    res = await build_action("waf_blacklist_ip", {"source": "from_event"}).execute(ctx)
    until = ctx.runner.calls[0][1]["deny_until"]
    assert before + 600 <= until <= int(time.time()) + 600 and res.data["until"] == until

    ctx0 = _ctx(FakeNetwork(), make_settings(waf_deny_file=str(f), waf_block_ttl_s=0))
    res0 = await build_action("waf_blacklist_ip", {"source": "from_event"}).execute(ctx0)
    assert ctx0.runner.calls[0][1]["deny_until"] == 0 and res0.data["until"] is None


@pytest.mark.anyio
async def test_block_purges_expired_entries_and_reloads_even_if_the_ip_was_already_there(tmp_path):
    f = deny(tmp_path, "198.51.100.2 1; # until=1", "198.51.100.1 1;")
    net = FakeNetwork()
    ctx = _ctx(net, make_settings(waf_deny_file=str(f)), changed=False)  # IP déjà bloquée
    res = await build_action("waf_block_ip", {"source": "from_event"}).execute(ctx)
    assert res.data["expired"] == ["198.51.100.2"]
    assert read_deny_file(f) == ["198.51.100.1"]
    assert ("POST", "/containers/cid-waf/kill") in net.docker_calls()  # purge => rechargement


@pytest.mark.anyio
async def test_purge_and_reload_is_silent_when_nothing_expired(tmp_path):
    f = deny(tmp_path, f"198.51.100.3 1; # until={NOW + 60}")
    net = FakeNetwork()
    http = httpx.AsyncClient(transport=httpx.MockTransport(net.handler))
    settings = make_settings(waf_deny_file=str(f))
    docker = DockerProxy(http, settings.docker_proxy_url)
    assert await purge_and_reload(settings, docker, LOG, now=NOW) == []
    assert net.docker_calls() == []  # rien retiré : pas de SIGHUP inutile
    assert await purge_and_reload(settings, docker, LOG, now=NOW + 60) == ["198.51.100.3"]
    assert net.docker_calls()[-1] == ("POST", "/containers/cid-waf/kill")


def test_startup_and_reads_purge_expired_blocks_and_reload_the_waf(tmp_path):
    env = Env(table=make_table(cooldown=0), verify=[True])
    f = deny(tmp_path, "198.51.100.1 1;", "198.51.100.2 1; # until=1")
    app = create_app(make_settings(waf_deny_file=str(f)), table=env.engine.table, services=env.services)
    with TestClient(app) as c:
        assert read_deny_file(f) == ["198.51.100.1"]  # purge au démarrage
        assert ("POST", "/containers/cid-waf/kill") in env.net.docker_calls()
        kills = len(env.net.docker_calls())
        with f.open("a", encoding="utf-8") as fh:
            fh.write("198.51.100.5 1; # until=2\n")  # échu entre deux relectures
        r = c.get("/waf/blocked-ips", headers=AUTH)
        assert [e["ip"] for e in r.json()["blocked"]] == ["198.51.100.1"]
        assert len(env.net.docker_calls()) > kills  # relecture => purge => rechargement
