"""Moteur : séquences d'actions, boucle de vérification, garde-fous, MTTD/MTTR, logs."""

from __future__ import annotations

from datetime import timedelta

import pytest
from broker_helpers import capture_logs
from conftest import T0, make_event, make_table
from prometheus_client import REGISTRY

pytestmark = pytest.mark.anyio


def counter(action: str, result: str) -> float:
    return REGISTRY.get_sample_value("resilience_remediation_actions_total", {"action": action, "result": result}) or 0.0


# ---------------------------------------------------------------- sélection / disponibilité vs corruption
async def test_service_flood_blocks_ip_then_restarts_and_never_restores(make_env):
    env = make_env(verify=[False, True])  # le blocage seul ne suffit pas -> action suivante (restart)
    sub = await env.run(make_event("service_flood"))
    inc = env.incident(sub.incident_id)

    assert env.action_types(sub.incident_id) == ["waf_block_ip", "restart_service"]
    assert [c[0] for c in env.runner.calls] == ["waf_deny_ip.yml"]  # jamais pg_restore
    assert env.runner.calls[0][1]["deny_ip"] == "203.0.113.7"
    assert ("POST", "/containers/cid-payment-api/restart") in env.net.docker_calls()
    assert inc["status"] == "closed"


async def test_data_corruption_restores_dump_and_never_touches_availability(make_env):
    env = make_env(verify=[True])
    sub = await env.run(make_event("data_corruption", source_ip=None))

    assert env.action_types(sub.incident_id) == ["restore_pg_dump"]
    assert env.runner.calls == [("pg_restore.yml", {"backup": "latest", "incident_id": sub.incident_id})]
    assert env.net.docker_calls() == []  # aucun restart / recreate
    assert env.incident(sub.incident_id)["status"] == "closed"


@pytest.mark.parametrize("itype,expected,verify", [
    # auth_abuse : verify KO après le blocage -> on enchaîne sur le durcissement du rate-limit
    ("auth_abuse", ["waf_block_ip", "tighten_rate_limit"], [False, True]),
    # web_attack : confirm_waf_block est en lecture seule (pas de vérification), blacklist modifie l'état
    ("web_attack", ["confirm_waf_block", "waf_blacklist_ip"], [True]),
    ("unknown", ["dry_run_report"], [True]),
])
async def test_other_types_run_their_own_sequence(make_env, itype, expected, verify):
    env = make_env(verify=verify)
    sub = await env.run(make_event(itype))
    assert env.action_types(sub.incident_id) == expected
    assert env.incident(sub.incident_id)["status"] == "closed"
    assert "restore_pg_dump" not in env.action_types(sub.incident_id)


async def test_tighten_rate_limit_uses_internal_token_and_idempotency_key(make_env):
    env = make_env(verify=[False, True])
    sub = await env.run(make_event("auth_abuse"))
    req = next(r for r in env.net.requests if r.url.host == "auth")
    assert req.url.path == "/internal/tighten-rate-limit"
    assert req.headers["X-Internal-Token"] == env.settings.internal_token
    assert req.headers["Idempotency-Key"] == sub.incident_id


# ---------------------------------------------------------------- boucle de vérification
async def test_verify_ok_closes_incident_and_computes_mttd_mttr(make_env):
    env = make_env(verify=[True], verify_cost_s=4.0)
    # détecté 3 s avant que le moteur ne reçoive l'événement
    env.clock.now = T0 + timedelta(seconds=3)
    sub = await env.run(make_event("data_corruption", ts=T0, source_ip=None))
    inc = env.incident(sub.incident_id)

    assert inc["status"] == "closed"
    assert inc["mttd_seconds"] == pytest.approx(3.0)   # détection -> 1re action
    assert inc["mttr_seconds"] == pytest.approx(7.0)   # détection -> verify OK (3 + 4 s de verify)
    lbl = {"incident_id": sub.incident_id}
    assert REGISTRY.get_sample_value("resilience_mttd_seconds", lbl) == pytest.approx(3.0)
    assert REGISTRY.get_sample_value("resilience_mttr_seconds", lbl) == pytest.approx(7.0)
    assert env.verifier.calls == 1


async def test_verify_ko_moves_to_next_action_then_stops_when_ok(make_env):
    env = make_env(verify=[False, True])
    sub = await env.run(make_event("service_flood"))
    assert env.action_types(sub.incident_id) == ["waf_block_ip", "restart_service"]
    assert env.verifier.calls == 2
    assert env.incident(sub.incident_id)["status"] == "closed"


async def test_verify_ok_after_first_action_skips_remaining_actions(make_env):
    env = make_env(verify=[True])
    sub = await env.run(make_event("service_flood"))
    assert env.action_types(sub.incident_id) == ["waf_block_ip"]  # pas de redémarrage inutile
    # Seul le rechargement à chaud du WAF (SIGHUP) est passé par le proxy : aucun restart.
    assert env.net.docker_calls() == [("GET", "/containers/json"), ("POST", "/containers/cid-waf/kill")]


async def test_failed_action_does_not_block_next_action(make_env):
    env = make_env(verify=[True], runner_ok=False)  # le playbook WAF échoue
    sub = await env.run(make_event("service_flood"))
    inc = env.incident(sub.incident_id)
    assert [(a["type"], a["result"]) for a in inc["actions"]] == [
        ("waf_block_ip", "failure"), ("restart_service", "success")]
    assert inc["status"] == "closed"


async def test_verification_retries_until_platform_is_healthy(make_env):
    from conftest import make_settings

    env = make_env(verify=[False, False, True], settings=make_settings(verify_retries=5))
    sub = await env.run(make_event("data_corruption", source_ip=None))
    assert env.verifier.calls == 3
    assert env.incident(sub.incident_id)["status"] == "closed"
    assert len(env.incident(sub.incident_id)["verifications"]) == 3


# ---------------------------------------------------------------- garde-fous
async def test_cooldown_blocks_second_close_action(make_env):
    env = make_env(table=make_table(cooldown=60), verify=[True])
    first = await env.run(make_event("service_flood"))
    actions_before = len(env.runner.calls)
    env.clock.advance(10)  # 10 s < 60 s

    second = await env.run(make_event("service_flood"))
    assert second.decision == "cooldown"
    assert second.incident_id == first.incident_id
    assert len(env.runner.calls) == actions_before  # aucune ré-action
    assert len(env.journal.list_incidents()) == 1

    env.clock.advance(61)  # cooldown écoulé -> nouvel incident autorisé
    third = await env.run(make_event("service_flood"))
    assert third.decision == "started" and third.incident_id != first.incident_id


async def test_cooldown_is_per_incident_key(make_env):
    env = make_env(table=make_table(cooldown=60), verify=[True])
    await env.run(make_event("service_flood"))
    other = await env.run(make_event("data_corruption", source_ip=None))
    assert other.decision == "started"  # un autre type d'incident n'est pas bloqué


async def test_duplicate_event_while_incident_in_progress_is_ignored(make_env):
    env = make_env(verify=[True])
    first = await env.engine.handle_event(make_event("service_flood"))
    dup = await env.engine.handle_event(make_event("service_flood"))
    assert (first.decision, dup.decision) == ("started", "duplicate")
    assert dup.incident_id == first.incident_id
    await env.engine.wait(first.incident_id)
    assert len(env.journal.list_incidents()) == 1


async def test_replayed_event_id_is_idempotent(make_env):
    env = make_env(verify=[True])
    ev = make_event("data_corruption", source_ip=None, event_id="11111111-1111-4111-8111-111111111111")
    first = await env.run(ev)
    again = await env.engine.handle_event(ev)
    assert again.decision == "replayed" and again.incident_id == first.incident_id
    assert len(env.runner.calls) == 1


async def test_max_attempts_triggers_escalation(make_env):
    env = make_env(table=make_table(cooldown=30, max_attempts=2), verify=[False])
    with capture_logs() as logs:
        sub = await env.run(make_event("data_corruption", source_ip=None))
    inc = env.incident(sub.incident_id)

    assert inc["status"] == "escalated"
    assert inc["attempts"] == 2
    restores = [a for a in inc["actions"] if a["type"] == "restore_pg_dump"]
    assert len(restores) == 2  # exactement max_attempts tentatives, pas une de plus
    assert inc["actions"][-1]["type"] == "notify_operator"
    assert env.sleeps == [30]  # cooldown respecté entre les deux tentatives
    assert [entry["event"] for entry in logs if entry["event"] == "remediation_failed"] == ["remediation_failed"]
    assert inc["mttr_seconds"] is None
    assert "remediation_verified" not in {entry["event"] for entry in logs}


async def test_escalation_when_every_action_fails(make_env):
    env = make_env(table=make_table(cooldown=0, max_attempts=1), verify=[True], runner_ok=False)
    sub = await env.run(make_event("data_corruption", source_ip=None))
    assert env.incident(sub.incident_id)["status"] == "escalated"
    assert env.verifier.calls == 0  # pas de vérification après une action en échec


async def test_dry_run_executes_nothing_destructive(make_env):
    env = make_env(table=make_table(dry_run=True), verify=[True])
    sub = await env.run(make_event("service_flood"))
    inc = env.incident(sub.incident_id)

    assert sub.dry_run is True
    assert env.runner.calls == []          # ni WAF, ni pg_restore
    assert env.net.docker_calls() == []    # ni restart
    assert env.verifier.calls == 0
    assert inc["status"] == "dry_run" and inc["dry_run"] is True
    assert [a["result"] for a in inc["actions"]] == ["dry_run", "dry_run"]
    assert inc["mttr_seconds"] is None


async def test_dry_run_forced_by_environment_cannot_be_disabled_by_table(make_env):
    from conftest import make_settings

    env = make_env(table=make_table(dry_run=False), settings=make_settings(dry_run=True))
    sub = await env.run(make_event("data_corruption", source_ip=None))
    assert env.runner.calls == [] and env.incident(sub.incident_id)["status"] == "dry_run"


async def test_dry_run_still_allows_read_only_actions(make_env):
    env = make_env(table=make_table(dry_run=True))
    sub = await env.run(make_event("web_attack"))
    inc = env.incident(sub.incident_id)
    assert [a["result"] for a in inc["actions"]] == ["success", "dry_run"]  # confirm (lecture) vs blacklist (bloquée)
    assert env.runner.calls == []


# ---------------------------------------------------------------- sécurité des actions
async def test_waf_never_blocks_protected_or_missing_ips(make_env):
    env = make_env(verify=[True])
    sub = await env.run(make_event("service_flood", source_ip="192.168.137.1"))  # l'hôte lui-même
    first = env.incident(sub.incident_id)["actions"][0]
    assert first["result"] == "failure" and "protégée" in first["detail"]
    assert env.runner.calls == []

    env2 = make_env(verify=[True])
    sub2 = await env2.run(make_event("service_flood", source_ip=None))
    assert "source_ip" in env2.incident(sub2.incident_id)["actions"][0]["detail"]


async def test_restart_refuses_service_outside_allow_list(make_env):
    from conftest import make_settings

    def mutate(d):
        for r in d["rules"]:
            if r["incident_type"] == "service_flood":
                r["actions"][1]["params"]["service"] = "postgres"

    env = make_env(table=make_table(max_attempts=1, mutate=mutate), verify=[True], runner_ok=False,
                   settings=make_settings())
    sub = await env.run(make_event("service_flood"))
    restart = next(a for a in env.incident(sub.incident_id)["actions"] if a["type"] == "restart_service")
    assert restart["result"] == "failure" and "liste autorisée" in restart["detail"]
    assert env.net.docker_calls() == []


# ---------------------------------------------------------------- logs / métriques / timeline
async def test_contract_log_events_and_metrics(make_env):
    env = make_env(verify=[False, True])
    restart_before, block_before = counter("restart_service", "success"), counter("waf_block_ip", "success")
    with capture_logs() as logs:
        sub = await env.run(make_event("service_flood"))
    events = [entry["event"] for entry in logs]
    assert events[0] == "remediation_started"
    assert events.count("remediation_action") == 2
    assert events[-1] == "remediation_verified"
    assert all(entry["incident_id"] == sub.incident_id for entry in logs)
    assert all({"ts", "level", "service", "event", "message", "request_id"} <= entry.keys() for entry in logs)
    assert counter("restart_service", "success") == restart_before + 1
    assert counter("waf_block_ip", "success") == block_before + 1


async def test_timeline_covers_detection_decision_action_verification_closure(make_env):
    env = make_env(verify=[False, True])
    q = env.broker.subscribe()
    sub = await env.run(make_event("service_flood"))
    phases = [r["phase"] for r in env.journal.timeline_since(0, sub.incident_id)]
    assert phases[0:2] == ["detection", "decision"]
    assert {"action", "verification"} <= set(phases) and phases[-1] == "closure"
    assert q.qsize() == len(phases)  # tout ce qui est journalisé est diffusé en direct
    ids = [r["id"] for r in env.journal.timeline_since(0)]
    assert ids == sorted(ids)
