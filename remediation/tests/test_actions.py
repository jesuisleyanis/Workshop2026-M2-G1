"""Actions unitaires : proxy Docker (liste blanche), garde-fous, vérificateur, journal."""

from __future__ import annotations

import logging
import stat
import sys
from pathlib import Path
from unittest.mock import ANY

import httpx
import pytest
from actions import REGISTRY, build_action
from actions.base import ActionContext, ActionError, ActionParamError
from actions.docker_proxy import DockerProxy, DockerProxyError
from actions.runner import AnsibleRunnerAdapter
from broker_helpers import capture_logs
from conftest import FakeNetwork, FakeRunner, make_event, make_settings, waf_blocked_entry
from journal import Journal
from verify import ScriptVerifier

pytestmark = pytest.mark.anyio


def ctx_for(http, settings=None, event=None, **extra) -> ActionContext:
    settings = settings or make_settings()
    return ActionContext(
        settings=settings, http=http,
        docker=DockerProxy(http, settings.docker_proxy_url, settings.docker_allow_recreate),
        runner=FakeRunner(), log=logging.getLogger("remediation-test"), event=event, incident_id="inc-1", extra=extra)


def client(net: FakeNetwork) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(net.handler))


def test_catalogue_contains_every_contract_action():
    assert set(REGISTRY) == {"restart_service", "recreate_service", "waf_block_ip", "waf_blacklist_ip",
                             "tighten_rate_limit", "restore_pg_dump", "confirm_waf_block",
                             "dry_run_report", "notify_operator"}
    assert {t for t, c in REGISTRY.items() if not c.mutating} == {"confirm_waf_block", "dry_run_report", "notify_operator"}


# ------------------------------------------------------------------ docker-socket-proxy
async def test_proxy_client_only_allows_restart_verbs_by_default():
    net = FakeNetwork()
    docker = DockerProxy(client(net), "http://docker-socket-proxy:2375")
    await docker.restart("abc123")
    assert net.docker_calls() == [("POST", "/containers/abc123/restart")]
    for method, path in [("DELETE", "/containers/abc123"), ("POST", "/containers/create"),
                         ("POST", "/containers/abc123/exec"), ("POST", "/containers/abc123/kill"),
                         ("GET", "/images/json"), ("POST", "/containers/abc123/stop")]:
        with pytest.raises(DockerProxyError, match="non autorisé"):
            await docker._call(method, path)
    assert len(net.docker_calls()) == 1  # rien d'autre n'est parti sur le réseau


async def test_proxy_client_allows_kill_only_with_sighup():
    net = FakeNetwork()
    docker = DockerProxy(client(net), "http://docker-socket-proxy:2375")
    await docker.reload("cid-waf")
    assert net.docker_calls() == [("POST", "/containers/cid-waf/kill")]
    assert net.requests[-1].url.params["signal"] == "HUP"
    for params in (None, {"signal": "KILL"}, {"signal": "TERM"}):
        with pytest.raises(DockerProxyError, match="signal=HUP"):
            await docker._call("POST", "/containers/cid-waf/kill", params=params)
    assert len(net.docker_calls()) == 1


async def test_waf_block_ip_runs_playbook_then_reloads_waf_only_when_changed():
    net = FakeNetwork()
    ctx = ctx_for(client(net), event=make_event(source_ip="203.0.113.9"))
    res = await build_action("waf_block_ip", {"source": "from_event"}).execute(ctx)
    assert res.ok and res.changed is True
    assert ctx.runner.calls == [("waf_deny_ip.yml", {"deny_ip": "203.0.113.9", "deny_list": "temporary",
                                                     "incident_id": "inc-1", "deny_until": ANY})]
    assert net.docker_calls() == [("GET", "/containers/json"), ("POST", "/containers/cid-waf/kill")]
    assert res.data["reloaded"] == ["cid-waf"]

    # IP déjà présente : playbook changed=False -> pas de rechargement inutile du WAF.
    net2 = FakeNetwork()
    ctx2 = ctx_for(client(net2), event=make_event(source_ip="203.0.113.9"))
    ctx2.runner.changed = False
    res2 = await build_action("waf_blacklist_ip", {"source": "from_event"}).execute(ctx2)
    assert res2.ok and res2.changed is False and "déjà bloquée" in res2.detail
    assert net2.docker_calls() == [] and ctx2.runner.calls[0][1]["deny_list"] == "permanent"

    # Deny-list écrite mais proxy en échec : l'action échoue explicitement (pas de faux succès).
    net3 = FakeNetwork()
    net3.handler_orig = net3.handler
    net3.handler = lambda r: httpx.Response(500) if r.url.path.endswith("/kill") else net3.handler_orig(r)
    with pytest.raises(ActionError, match="rechargement du WAF impossible"):
        await build_action("waf_block_ip", {"source": "from_event"}).execute(
            ctx_for(client(net3), event=make_event(source_ip="203.0.113.9")))


async def test_recreate_is_disabled_without_wider_proxy_profile():
    net = FakeNetwork()
    ctx = ctx_for(client(net))
    with pytest.raises(ActionError, match="restart seul"):
        await build_action("recreate_service", {"service": "payment-api"}).execute(ctx)


async def test_restart_resolves_compose_service_and_reports_proxy_failure():
    net = FakeNetwork()
    res = await build_action("restart_service", {"service": "auth"}).execute(ctx_for(client(net)))
    assert res.ok and ("POST", "/containers/cid-auth/restart") in net.docker_calls()

    net.restart_status = 500
    with pytest.raises(ActionError, match="HTTP 500"):
        await build_action("restart_service", {"service": "auth"}).execute(ctx_for(client(net)))


class RecreateNet(FakeNetwork):
    def __init__(self, create_status: int = 201) -> None:
        super().__init__()
        self.create_status = create_status

    def handler(self, request):
        self.requests.append(request)
        p = request.url.path
        if p == "/containers/json":
            return httpx.Response(200, json=[{"Id": "old1234567890"}])
        if p == "/containers/old1234567890/json":
            return httpx.Response(200, json={"Id": "old1234567890", "Name": "/payment-api",
                "Config": {"Image": "payment-api:good", "Env": ["A=1"], "Labels": {"x": "y"}},
                "HostConfig": {"NetworkMode": "app"},
                "NetworkSettings": {"Networks": {"app": {"Aliases": ["payment-api", "old123456789"]}}}})
        if p == "/containers/create":
            return httpx.Response(self.create_status, json={"Id": "new1"})
        return httpx.Response(204)


async def test_recreate_happy_path_and_rollback():
    net = RecreateNet()
    s = make_settings(docker_allow_recreate=True)
    res = await build_action("recreate_service", {"service": "payment-api"}).execute(ctx_for(client(net), s))
    assert res.ok
    seq = net.docker_calls()
    assert seq.index(("POST", "/containers/create")) < seq.index(("DELETE", "/containers/old1234567890"))
    create = next(r for r in net.requests if r.url.path == "/containers/create")
    assert b"payment-api:good" in create.content and b"old123456789" not in create.content

    bad = RecreateNet(create_status=500)
    with pytest.raises(ActionError):
        await build_action("recreate_service", {"service": "payment-api"}).execute(ctx_for(client(bad), s))
    calls = bad.docker_calls()
    assert ("DELETE", "/containers/old1234567890") not in calls  # l'ancien conteneur est conservé
    assert calls[-1] == ("POST", "/containers/old1234567890/start")  # et remis en service


# ------------------------------------------------------------------ autres actions
async def test_tighten_rate_limit_failures():
    net = FakeNetwork()
    action = build_action("tighten_rate_limit", {"service": "auth", "factor": 0.5})
    with pytest.raises(ActionError, match="INTERNAL_TOKEN"):
        await action.execute(ctx_for(client(net), make_settings(internal_token=None)))
    net.auth_status = 500
    with pytest.raises(ActionError, match="HTTP 500"):
        await action.execute(ctx_for(client(net)))


async def test_confirm_waf_block_reads_loki_only():
    net = FakeNetwork()
    res = await build_action("confirm_waf_block", {}).execute(ctx_for(client(net), event=make_event("web_attack")))
    assert res.ok and res.data["confirmed"] is True
    assert {r.method for r in net.requests} == {"GET"}
    query = net.requests[0].url.params["query"]
    assert "203.0.113.7" in query
    # Sélecteur réel des logs waf_blocked : émis par le conteneur waf-exporter (label Promtail).
    assert query.startswith('{service="waf-exporter", event="waf_blocked"}')
    net.loki_values = []
    res = await build_action("confirm_waf_block", {}).execute(ctx_for(client(net)))
    assert res.ok and res.data["confirmed"] is False


async def test_notify_operator_logs_remediation_failed_and_posts_webhook():
    net = FakeNetwork()
    settings = make_settings(notify_webhook_url="http://dashboard/hook")
    with capture_logs() as logs:
        await build_action("notify_operator", {}).execute(ctx_for(client(net), settings, reason="boom"))
    assert logs[0]["event"] == "remediation_failed" and logs[0]["level"] == "ERROR"
    assert logs[0]["incident_id"] == "inc-1" and "boom" in logs[0]["message"]
    assert net.requests[0].url.host == "dashboard"


@pytest.mark.parametrize("action,params", [
    ("restore_pg_dump", {"backup": "../../etc/passwd"}),
    ("restore_pg_dump", {"backup": "a;rm -rf /"}),
    ("restart_service", {"service": "Bad Name; ls"}),
    ("restart_service", {}),
    ("tighten_rate_limit", {"service": "payment-api", "factor": 0.5}),
    ("tighten_rate_limit", {"service": "auth", "factor": 1.5}),
    ("waf_block_ip", {"source": "10.0.0.0/8"}),
    ("nope", {}),
])
def test_param_validation_rejects_dangerous_values(action, params):
    with pytest.raises(ActionParamError):
        build_action(action, params)


# ------------------------------------------------------------------ ansible / verify_tx / journal
async def test_ansible_adapter_refuses_non_whitelisted_playbook():
    res = await AnsibleRunnerAdapter("/nonexistent").run_playbook("../../evil.yml", {})
    assert res.ok is False and "non autorisé" in res.detail


def script(tmp_path, body: str):
    p = tmp_path / "verify_tx"
    p.write_text(f"#!/bin/sh\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


@pytest.mark.skipif(sys.platform == "win32", reason="script à shebang POSIX (/bin/sh) ; la prod tourne en conteneur Linux")
async def test_script_verifier_follows_exit_code_contract(tmp_path):
    ok = await ScriptVerifier(script(tmp_path, "echo OK; exit 0")).run()
    assert ok.ok and ok.rc == 0 and ok.detail == "OK"
    ko = await ScriptVerifier(script(tmp_path, "echo KO; exit 1")).run()
    assert not ko.ok and ko.rc == 1
    assert not (await ScriptVerifier(str(tmp_path / "absent")).run()).ok
    slow = await ScriptVerifier(script(tmp_path, "sleep 5"), timeout_s=0.2).run()
    assert not slow.ok and "timeout" in slow.detail


def test_journal_marks_orphans_interrupted_after_restart():
    from conftest import T0

    j = Journal(":memory:")
    j.create_incident(incident_id="i1", key="k", incident_type="unknown", service="s", event_id="e",
                      event_json="{}", detected_at=T0, dry_run=False)
    assert j.recover_orphans() == 1
    assert j.get_incident("i1")["status"] == "interrupted"


async def test_restart_is_rolling_one_replica_at_a_time():
    # 3 répliques derrière le WAF : redémarrer tout d'un coup = coupure ; une à une, attente « healthy ».
    net = FakeNetwork()
    net.replicas["payment-api"] = 3
    res = await build_action("restart_service", {"service": "payment-api"}).execute(ctx_for(client(net)))
    assert res.ok and len(res.data["containers"]) == 3
    calls = [(m, p) for m, p in net.docker_calls() if p != "/containers/json"]
    assert calls == [
        ("POST", "/containers/cid-payment-api-1/restart"), ("GET", "/containers/cid-payment-api-1/json"),
        ("POST", "/containers/cid-payment-api-2/restart"), ("GET", "/containers/cid-payment-api-2/json"),
        ("POST", "/containers/cid-payment-api-3/restart"),
    ]


async def test_rolling_restart_stops_if_a_replica_never_recovers(monkeypatch):
    import actions.docker as docker_actions

    monkeypatch.setattr(docker_actions, "ROLLING_HEALTH_TIMEOUT_S", 0.0)
    net = FakeNetwork()
    net.replicas["payment-api"] = 3
    net.health = "unhealthy"
    with pytest.raises(ActionError, match="interrompu"):
        await build_action("restart_service", {"service": "payment-api"}).execute(ctx_for(client(net)))
    restarts = [p for m, p in net.docker_calls() if p.endswith("/restart")]
    assert restarts == ["/containers/cid-payment-api-1/restart"]  # on n'abat pas les autres répliques


# ------------------------------------------------------------------ source `from_loki` (web_attack)
async def test_from_loki_blocks_the_most_frequent_waf_blocked_source():
    net = FakeNetwork()
    net.loki_values = [waf_blocked_entry("198.51.100.9")] + [waf_blocked_entry("203.0.113.50")] * 4
    ctx = ctx_for(client(net), event=make_event("web_attack", source_ip=None))
    res = await build_action("waf_blacklist_ip", {"source": "from_loki"}).execute(ctx)
    assert res.ok and res.data["ip"] == "203.0.113.50" and res.data["list"] == "permanent"
    assert ctx.runner.calls == [("waf_deny_ip.yml", {"deny_ip": "203.0.113.50", "deny_list": "permanent",
                                                     "incident_id": "inc-1", "deny_until": ANY})]
    loki = [r for r in net.requests if r.url.host == "loki"]
    assert len(loki) == 1 and loki[0].method == "GET"
    assert loki[0].url.params["query"] == '{service="waf-exporter", event="waf_blocked"}'
    assert net.docker_calls()[-1] == ("POST", "/containers/cid-waf/kill")  # rechargement par SIGHUP


async def test_from_loki_ignores_garbage_lines_and_folds_ipv4_mapped():
    net = FakeNetwork()
    net.loki_values = [["1", "pas du json"], ["2", '{"client_ip": "pas-une-ip"}'], ["3", "[1]"], ["4"],
                       waf_blocked_entry("::ffff:203.0.113.8"), waf_blocked_entry("203.0.113.8")]
    ctx = ctx_for(client(net), event=make_event("web_attack", source_ip=None))
    res = await build_action("waf_blacklist_ip", {"source": "from_loki"}).execute(ctx)
    assert res.data["ip"] == "203.0.113.8"


async def test_from_loki_never_blocks_protected_addresses():
    for protected in ("192.168.137.1", "::ffff:192.168.137.1", "127.0.0.1"):
        net = FakeNetwork()
        net.loki_values = [waf_blocked_entry(protected)] * 3
        ctx = ctx_for(client(net), event=make_event("web_attack", source_ip=None))
        with pytest.raises(ActionError, match="protégée"):
            await build_action("waf_blacklist_ip", {"source": "from_loki"}).execute(ctx)
        assert ctx.runner.calls == [] and net.docker_calls() == []


async def test_from_loki_without_events_or_with_loki_down_fails_cleanly():
    net = FakeNetwork()
    net.loki_values = []
    ctx = ctx_for(client(net), event=make_event("web_attack", source_ip=None))
    with pytest.raises(ActionError, match="aucun événement waf_blocked"):
        await build_action("waf_blacklist_ip", {"source": "from_loki"}).execute(ctx)

    def down(request):
        raise httpx.ConnectError("loki injoignable")

    ctx2 = ctx_for(httpx.AsyncClient(transport=httpx.MockTransport(down)), event=make_event("web_attack"))
    with pytest.raises(ActionError, match="logs WAF illisibles"):
        await build_action("waf_blacklist_ip", {"source": "from_loki"}).execute(ctx2)
    assert ctx.runner.calls == [] and ctx2.runner.calls == []


async def test_from_loki_plan_does_not_query_loki():
    net = FakeNetwork()
    plan = await build_action("waf_blacklist_ip", {"source": "from_loki"}).plan(ctx_for(client(net)))
    assert "Loki" in plan and net.requests == []


def test_source_param_accepts_from_loki_and_still_rejects_networks():
    build_action("waf_blacklist_ip", {"source": "from_loki"})
    for bad in ("10.0.0.0/8", "from_header", "evil.example"):
        with pytest.raises(ActionParamError):
            build_action("waf_block_ip", {"source": bad})


# ------------------------------------------------------------------ source `from_event_or_loki` (web_attack)
async def test_from_event_or_loki_prefers_the_ip_designated_by_the_detector():
    net = FakeNetwork()
    net.loki_values = [waf_blocked_entry("203.0.113.50")] * 4
    ctx = ctx_for(client(net), event=make_event("web_attack", source_ip="198.51.100.23"))
    res = await build_action("waf_blacklist_ip", {"source": "from_event_or_loki"}).execute(ctx)
    assert res.ok and res.data["ip"] == "198.51.100.23"
    assert [r for r in net.requests if r.url.host == "loki"] == []  # pas de requête Loki inutile


async def test_from_event_or_loki_falls_back_to_loki_without_source_ip():
    net = FakeNetwork()
    net.loki_values = [waf_blocked_entry("203.0.113.50")] * 4
    ctx = ctx_for(client(net), event=make_event("web_attack", source_ip=None))
    res = await build_action("waf_blacklist_ip", {"source": "from_event_or_loki"}).execute(ctx)
    assert res.ok and res.data["ip"] == "203.0.113.50"


async def test_from_event_or_loki_never_blocks_the_edge_gateway():
    # Docker Desktop : tous les clients externes entrent avec l'IP de la passerelle d'`edge`. La bloquer
    # couperait tout le monde (jury compris) alors que verify_tx, qui passe par `app`, resterait vert.
    import yaml

    compose = yaml.safe_load((Path(__file__).resolve().parents[2] / "infra/compose/docker-compose.yml")
                             .read_text(encoding="utf-8"))
    gateway = compose["networks"]["edge"]["ipam"]["config"][0]["gateway"]
    never = tuple(compose["services"]["remediation"]["environment"]["NEVER_BLOCK_IPS"].split(","))
    for event_ip, loki_ip in ((gateway, "203.0.113.50"), (None, gateway)):
        net = FakeNetwork()
        net.loki_values = [waf_blocked_entry(loki_ip)] * 4
        ctx = ctx_for(client(net), event=make_event("web_attack", source_ip=event_ip),
                      settings=make_settings(never_block_ips=never))
        with pytest.raises(ActionError, match="protégée"):
            await build_action("waf_blacklist_ip", {"source": "from_event_or_loki"}).execute(ctx)
        assert ctx.runner.calls == [] and net.docker_calls() == []


async def test_from_event_or_loki_plan_names_the_event_ip_without_querying_loki():
    net = FakeNetwork()
    action = build_action("waf_blacklist_ip", {"source": "from_event_or_loki"})
    plan = await action.plan(ctx_for(client(net), event=make_event("web_attack", source_ip="198.51.100.23")))
    assert "198.51.100.23" in plan
    plan = await action.plan(ctx_for(client(net), event=make_event("web_attack", source_ip=None)))
    assert "Loki" in plan and net.requests == []



async def test_confirm_waf_block_require_fails_without_any_blocked_event():
    net = FakeNetwork()
    net.loki_values = []
    with pytest.raises(ActionError, match="attaque non contenue"):
        await build_action("confirm_waf_block", {"require": True}).execute(ctx_for(client(net)))
    net.loki_values = [waf_blocked_entry("203.0.113.7")]
    res = await build_action("confirm_waf_block", {"require": True}).execute(ctx_for(client(net)))
    assert res.ok and res.data["confirmed"] is True
    with pytest.raises(ActionParamError):
        build_action("confirm_waf_block", {"require": "oui"})
