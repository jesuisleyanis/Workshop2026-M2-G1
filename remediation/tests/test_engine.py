"""Moteur : séquences d'actions, boucle de vérification, garde-fous, MTTD/MTTR, logs."""

from __future__ import annotations

from datetime import timedelta

import pytest
from broker_helpers import capture_logs
from conftest import T0, make_event, make_settings, make_table, waf_blocked_entry
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
    # web_attack : la liste noire (modifiante) est vérifiée et suffit ; la preuve en lecture seule n'est
    # jouée que si le blocage échoue
    ("web_attack", ["waf_blacklist_ip"], [True]),
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
    assert env.verifier.calls == 3  # pré-contrôle (KO) + après chaque action modifiante
    assert env.incident(sub.incident_id)["status"] == "closed"


async def test_contained_attack_is_closed_without_any_action(make_env):
    # Flood déjà écrêté par le WAF (service disponible) : aucun restart de payment-api.
    # Constaté le 21/10 sans ce pré-contrôle : 12 redémarrages en 20 min pendant un flood continu.
    env = make_env(precheck_ok=True)
    sub = await env.run(make_event("service_flood"))
    inc = env.incident(sub.incident_id)
    assert inc["status"] == "closed"
    assert env.action_types(sub.incident_id) == []
    assert env.verifier.calls == 1 and env.net.docker_calls() == []


async def test_types_without_verify_first_always_act(make_env):
    # data_corruption : une corruption ne se « contient » pas toute seule ; web_attack : compromission
    # tentée, ModSecurity renvoie déjà 403 (verify_tx passerait) mais l'attaquant doit être bloqué.
    env = make_env(verify=[True], precheck_ok=True)
    sub = await env.run(make_event("data_corruption"))
    assert env.action_types(sub.incident_id) == ["restore_pg_dump"]
    sub = await env.run(make_event("web_attack", service="waf", source_ip="198.51.100.23"))
    assert env.action_types(sub.incident_id) == ["waf_blacklist_ip"]


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
    # blacklist (modifiante) simulée ; la preuve en lecture seule s'exécute réellement
    assert [(a["type"], a["result"]) for a in inc["actions"]] == [
        ("waf_blacklist_ip", "dry_run"), ("confirm_waf_block", "success")]
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

    # La forme IPv4-mappée ne doit pas contourner la liste blanche (P4S-05).
    env3 = make_env(verify=[True])
    sub3 = await env3.run(make_event("service_flood", source_ip="::ffff:192.168.137.1"))
    first3 = env3.incident(sub3.incident_id)["actions"][0]
    assert first3["result"] == "failure" and "protégée" in first3["detail"]
    assert env3.runner.calls == []


async def test_waf_never_blocks_an_ip_inside_a_protected_network(make_env):
    # Constaté le 21/10 : le detector a désigné l'IP de la remédiation elle-même (trafic verify_tx) ;
    # bloquée, chaque vérification suivante aurait échoué. Les réseaux Docker internes sont protégés.
    from conftest import make_settings

    env = make_env(verify=[True], settings=make_settings(never_block_ips=("127.0.0.1", "172.31.0.0/24")))
    sub = await env.run(make_event("service_flood", source_ip="172.31.0.9"))
    first = env.incident(sub.incident_id)["actions"][0]
    assert first["result"] == "failure" and "protégée" in first["detail"]
    assert env.runner.calls == []


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


async def test_journal_remembers_successful_blocks_for_the_blocked_ips_card(make_env):
    env = make_env(verify=[True])
    sub = await env.run(make_event("auth_abuse", source_ip="203.0.113.9"))
    (block,) = env.journal.last_blocks()
    assert block["incident_id"] == sub.incident_id and block["incident_type"] == "auth_abuse"
    assert block["action_type"] == "waf_block_ip" and block["detail"].startswith("203.0.113.9 ")


# ---------------------------------------------------------------- web_attack : compromission tentée
async def test_web_attack_blocks_the_detector_ip_even_if_the_waf_already_contains_it(make_env):
    """Table RÉELLE. ModSecurity renvoie déjà 403 -> verify_tx passerait d'emblée : sans verify_first,
    l'attaquant (IP désignée par le detector) est quand même mis en liste noire, puis incident clos."""
    env = make_env(precheck_ok=True)
    sub = await env.run(make_event("web_attack", service="waf", source_ip="198.51.100.23"))
    inc = env.incident(sub.incident_id)
    assert env.action_types(sub.incident_id) == ["waf_blacklist_ip"]
    assert env.runner.calls == [("waf_deny_ip.yml", {"deny_ip": "198.51.100.23", "deny_list": "permanent",
                                                     "incident_id": sub.incident_id})]
    assert inc["status"] == "closed"


async def test_web_attack_falls_back_to_the_loki_source_without_source_ip(make_env):
    env = make_env(verify=[True])
    env.net.loki_values = [waf_blocked_entry("203.0.113.50")] * 4 + [waf_blocked_entry("198.51.100.2")]
    sub = await env.run(make_event("web_attack", service="waf", source_ip=None))
    inc = env.incident(sub.incident_id)
    assert env.action_types(sub.incident_id) == ["waf_blacklist_ip"]
    assert env.runner.calls == [("waf_deny_ip.yml", {"deny_ip": "203.0.113.50", "deny_list": "permanent",
                                                     "incident_id": sub.incident_id})]
    assert inc["status"] == "closed"


async def test_web_attack_from_an_unblockable_ip_is_closed_once_containment_is_proven(make_env):
    # Docker Desktop sans mode IP réelle : l'attaquant a l'IP (protégée) de la passerelle. Pas de blocage
    # possible, mais ModSecurity a bloqué (preuve Loki) et verify_tx passe -> clos, échec du blocage tracé.
    env = make_env(verify=[True], settings=make_settings(never_block_ips=("172.30.0.0/24",)))
    env.net.loki_values = [waf_blocked_entry("172.30.0.1")] * 5
    sub = await env.run(make_event("web_attack", service="waf", source_ip=None))
    inc = env.incident(sub.incident_id)
    assert [(a["type"], a["result"]) for a in inc["actions"]] == [
        ("waf_blacklist_ip", "failure"), ("confirm_waf_block", "success")]
    assert "protégée" in inc["actions"][0]["detail"]
    assert env.runner.calls == [] and inc["status"] == "closed"


async def test_web_attack_without_any_blocked_event_escalates(make_env):
    # Aucun blocage observé : rien ne prouve que l'attaque soit contenue -> pas de clôture.
    env = make_env(table=make_table(cooldown=0, max_attempts=1), verify=[True])
    env.net.loki_values = []
    sub = await env.run(make_event("web_attack", service="waf", source_ip=None))
    inc = env.incident(sub.incident_id)
    assert inc["status"] == "escalated" and env.runner.calls == []
    assert "aucun événement waf_blocked" in inc["actions"][0]["detail"]
    assert "attaque non contenue" in inc["actions"][1]["detail"]
