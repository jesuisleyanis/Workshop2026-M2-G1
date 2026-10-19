"""Liste de blocage du WAF : écriture atomique, source `from_loki`, chaîne web_attack de bout en bout.

Le moteur n'a ni docker exec ni accès à l'hôte : il écrit le fichier lu par nginx (dossier
partagé) et le WAF se recharge seul. Ces tests couvrent la moitié « moteur » de la chaîne ;
la moitié « WAF » (rechargement, nginx -t) est testée sur la vraie image (security/waf/tests).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re

import httpx
import pytest
from actions import build_action
from actions.base import ActionError, ActionParamError
from actions.blocklist import BlocklistFile
from actions.docker_proxy import DockerProxy
from actions.waf import resolve_target, top_blocked_ip
from conftest import (
    FakeBlocklist,
    FakeNetwork,
    FakeRunner,
    make_event,
    make_settings,
    waf_blocked_entry,
)
from engine import Services

pytestmark = pytest.mark.anyio


def ip_lines(path) -> list[str]:
    return [m.group(1) for line in path.read_text(encoding="utf-8").splitlines()
            if (m := re.match(r"^\s*([0-9a-fA-F:.]+)\s+1\s*;", line))]


# ------------------------------------------------------------------ écriture du fichier
async def test_add_writes_nginx_geo_line_and_is_idempotent(tmp_path):
    bl = BlocklistFile(tmp_path / "blocked_ips.conf")
    first = await bl.add("203.0.113.7", deny_list="permanent", incident_id="inc-1")
    again = await bl.add("203.0.113.7", deny_list="permanent", incident_id="inc-2")
    assert first.changed is True and again.changed is False and again.entries == 1
    assert ip_lines(tmp_path / "blocked_ips.conf") == ["203.0.113.7"]
    text = (tmp_path / "blocked_ips.conf").read_text(encoding="utf-8")
    assert "203.0.113.7 1; # list=permanent incident=inc-1 ts=" in text      # format `geo` + trace
    assert text.startswith("# ")                                              # en-tête, commentaires conservés


async def test_add_keeps_existing_entries_and_comments_and_ipv6(tmp_path):
    path = tmp_path / "blocked_ips.conf"
    path.write_text("# à la main\n198.51.100.9 1;\n", encoding="utf-8")        # sans retour final géré plus bas
    bl = BlocklistFile(path)
    await bl.add("2001:db8::1", deny_list="temporary", incident_id="inc-3")
    assert ip_lines(path) == ["198.51.100.9", "2001:db8::1"]
    assert "# à la main" in path.read_text(encoding="utf-8")
    # une IP déjà présente sous une autre écriture est reconnue (idempotence sur la forme canonique)
    res = await bl.add("2001:0db8:0000:0000:0000:0000:0000:0001", deny_list="temporary", incident_id="inc-4")
    assert res.changed is False


async def test_add_replaces_the_file_by_rename_so_a_directory_mount_sees_it(tmp_path):
    """Un renommage crée un nouvel inode : c'est pourquoi le WAF monte le DOSSIER, pas le fichier."""
    path = tmp_path / "blocked_ips.conf"
    bl = BlocklistFile(path)
    await bl.add("203.0.113.7", deny_list="permanent", incident_id="inc-1")
    before = os.stat(path)
    await bl.add("203.0.113.8", deny_list="permanent", incident_id="inc-1")
    after = os.stat(path)
    if os.name != "nt":  # st_ino n'est pas fiable sous Windows
        assert after.st_ino != before.st_ino
    assert not [p for p in tmp_path.iterdir() if p.name != "blocked_ips.conf"]  # aucun .tmp résiduel
    assert oct(after.st_mode & 0o777) == oct(0o644) or os.name == "nt"           # lisible par l'uid nginx


async def test_concurrent_adds_lose_nothing(tmp_path):
    path = tmp_path / "blocked_ips.conf"
    bl = BlocklistFile(path)
    ips = [f"203.0.113.{n}" for n in range(1, 41)]
    await asyncio.gather(*(bl.add(ip, deny_list="temporary", incident_id="inc") for ip in ips))
    assert sorted(ip_lines(path)) == sorted(ips)


@pytest.mark.parametrize("bad", ["not-an-ip", "10.0.0.0/8", "1.2.3.4; deny all", "1.2.3.4 1;\n5.6.7.8", ""])
async def test_add_refuses_anything_that_is_not_a_single_ip(tmp_path, bad):
    bl = BlocklistFile(tmp_path / "blocked_ips.conf")
    with pytest.raises(ActionError):
        await bl.add(bad, deny_list="permanent", incident_id="inc")
    assert not (tmp_path / "blocked_ips.conf").exists()                          # rien d'écrit


async def test_comment_cannot_be_used_to_inject_a_line(tmp_path):
    bl = BlocklistFile(tmp_path / "blocked_ips.conf")
    await bl.add("203.0.113.7", deny_list="x\n6.6.6.6 1;", incident_id="inc\n7.7.7.7 1;")
    assert ip_lines(tmp_path / "blocked_ips.conf") == ["203.0.113.7"]


async def test_list_is_capped(tmp_path):
    bl = BlocklistFile(tmp_path / "blocked_ips.conf", max_entries=2)
    await bl.add("203.0.113.1", deny_list="temporary", incident_id="i")
    await bl.add("203.0.113.2", deny_list="temporary", incident_id="i")
    with pytest.raises(ActionError, match="pleine"):
        await bl.add("203.0.113.3", deny_list="temporary", incident_id="i")
    assert (await bl.add("203.0.113.1", deny_list="temporary", incident_id="i")).changed is False  # déjà là : ok


async def test_unwritable_directory_is_a_clean_action_error(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("fichier", encoding="utf-8")
    with pytest.raises(ActionError):
        await BlocklistFile(blocker / "blocked_ips.conf").add("203.0.113.7", deny_list="temporary", incident_id="i")


# ------------------------------------------------------------------ source `from_loki`
def ctx(net: FakeNetwork, *, event=None, blocklist=None, settings=None):
    from actions.base import ActionContext

    settings = settings or make_settings()
    http = httpx.AsyncClient(transport=httpx.MockTransport(net.handler))
    return ActionContext(settings=settings, http=http,
                         docker=DockerProxy(http, settings.docker_proxy_url, settings.docker_allow_recreate),
                         runner=FakeRunner(), log=logging.getLogger("remediation-test"), event=event,
                         incident_id="inc-1", blocklist=blocklist if blocklist is not None else FakeBlocklist())


async def test_top_blocked_ip_picks_the_most_frequent_source():
    net = FakeNetwork()
    net.loki_values = [waf_blocked_entry("198.51.100.9")] + [waf_blocked_entry("203.0.113.7")] * 5
    assert await top_blocked_ip(ctx(net)) == "203.0.113.7"
    req = net.requests[0]
    assert req.url.params["query"].startswith('{service="waf-exporter"}') and "waf_blocked" in req.url.params["query"]
    assert {r.method for r in net.requests} == {"GET"}                           # lecture seule


async def test_top_blocked_ip_ignores_garbage_lines():
    net = FakeNetwork()
    net.loki_values = [["1", "pas du json"], ["2", json.dumps({"client_ip": "pas-une-ip"})], ["3", json.dumps([1])],
                       ["4", json.dumps({"client_ip": None})], waf_blocked_entry("203.0.113.7")]
    assert await top_blocked_ip(ctx(net)) == "203.0.113.7"
    net.loki_values = []
    assert await top_blocked_ip(ctx(net)) is None


async def test_from_loki_resolution_applies_the_protected_address_guard():
    net = FakeNetwork()
    net.loki_values = [waf_blocked_entry("192.168.137.1")] * 3                   # l'hôte lui-même
    with pytest.raises(ActionError, match="protégée"):
        await resolve_target({"source": "from_loki"}, ctx(net))
    net.loki_values = []
    with pytest.raises(ActionError, match="introuvable"):
        await resolve_target({"source": "from_loki"}, ctx(net))


async def test_loki_down_is_a_clean_action_error():
    def boom(request):  # noqa: ARG001
        raise httpx.ConnectError("loki injoignable")

    from actions.base import ActionContext

    settings = make_settings()
    http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    c = ActionContext(settings=settings, http=http, docker=None, runner=FakeRunner(),
                      log=logging.getLogger("t"), event=None, incident_id="i", blocklist=FakeBlocklist())
    with pytest.raises(ActionError, match="illisibles"):
        await resolve_target({"source": "from_loki"}, c)


def test_source_param_accepts_from_loki_and_still_rejects_networks():
    build_action("waf_blacklist_ip", {"source": "from_loki"})
    build_action("waf_block_ip", {"source": "203.0.113.7"})
    with pytest.raises(ActionParamError):
        build_action("waf_block_ip", {"source": "10.0.0.0/8"})


async def test_waf_action_without_blocklist_fails_closed():
    c = ctx(FakeNetwork(), event=make_event("web_attack"))
    c.blocklist = None
    with pytest.raises(ActionError, match="BLOCKLIST_PATH"):
        await build_action("waf_blacklist_ip", {"source": "203.0.113.7"}).execute(c)


# ------------------------------------------------------------------ la chaîne web_attack, moteur réel
async def test_web_attack_chain_writes_the_attacker_ip_into_the_real_file(make_env, tmp_path):
    """Table de décision RÉELLE : web_attack -> confirm_waf_block -> waf_blacklist_ip(from_loki)
    -> fichier lu par nginx -> vérification. Le detector n'émet pas source_ip : l'IP vient de Loki."""
    env = make_env(verify=[True])
    real = BlocklistFile(tmp_path / "blocked_ips.conf")
    env.services.blocklist = real
    env.net.loki_values = [waf_blocked_entry("203.0.113.50")] * 4 + [waf_blocked_entry("198.51.100.2")]

    sub = await env.run(make_event("web_attack", source_ip=None))

    assert env.action_types(sub.incident_id) == ["confirm_waf_block", "waf_blacklist_ip"]
    assert ip_lines(tmp_path / "blocked_ips.conf") == ["203.0.113.50"]           # l'attaquant, pas l'autre
    assert "permanent" in (tmp_path / "blocked_ips.conf").read_text(encoding="utf-8")
    assert env.incident(sub.incident_id)["status"] == "closed"
    assert env.runner.calls == [] and env.net.docker_calls() == []               # ni Ansible ni Docker


async def test_web_attack_without_any_blocked_event_fails_and_escalates(make_env, tmp_path):
    env = make_env(verify=[True], table=None)
    env.services.blocklist = BlocklistFile(tmp_path / "blocked_ips.conf")
    env.net.loki_values = []
    sub = await env.run(make_event("web_attack", source_ip=None))
    blacklist = next(a for a in env.incident(sub.incident_id)["actions"] if a["type"] == "waf_blacklist_ip")
    assert blacklist["result"] == "failure" and "introuvable" in blacklist["detail"]
    assert not (tmp_path / "blocked_ips.conf").exists()


def test_services_blocklist_is_optional_for_other_callers():
    s = Services(http=None, docker=None, runner=None, verifier=None)
    assert s.blocklist is None
