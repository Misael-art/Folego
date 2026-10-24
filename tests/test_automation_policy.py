"""F6 policy: preset never widens grant; unknown/stale never authorizes."""
import pytest

from folego.core.snapshot import OK, MemInfo, Snapshot, SourceQuality
from folego.orchestration.automation import (AGUARDAR, DESLIGADO, EXECUTAR,
                                             RECUSAR, SIMULAR, SUSPENDER,
                                             Candidate, PRESETS, evaluate)
from folego.orchestration.models import ActionPlan, Grant, ResourceIdentity

NOW = 10_000.0
MONO = 500.0


def a_plan(**over):
    base = {"action": "tmpfs.release",
            "target": ResourceIdentity.path("/tmp/folego-agente-1000", dev=8, ino=42),
            "params": {"bytes": 4096}, "created_at": NOW - 10,
            "expires_at": NOW + 60}
    base.update(over)
    return ActionPlan(**base)


def a_grant(**over):
    base = {"grant_id": "g-1", "action": "tmpfs.release",
            "resources": (a_plan().target,), "limits": {"bytes": 4096}, "issued_at": NOW - 100,
            "expires_at": NOW + 3600}
    base.update(over)
    return Grant(**base)


def snap(*, mono=MONO, sources=None, total=1000, available=500):
    if sources is None:
        sources = (SourceQuality("meminfo", OK, "", mono),)
    return Snapshot(ts=NOW, mem=MemInfo(total, available), swap_used_kb=0,
                    swap_total_kb=0, pressure_memory=None, pressure_io=None,
                    pressure_cpu=None, load=None, apps=(), self_rss_kb=1,
                    mono=mono, sources=sources)


def candidate(**over):
    base = dict(plan=a_plan(), owner_verified=True, sustained_samples=5,
                observed_for_s=600, boot_id="boot-a", last_boot_id="boot-a")
    base.update(over)
    return Candidate(**base)


def decide(*, snapshot=None, cand=None, mode="automatico", preset="equilibrado",
           grant=None):
    return evaluate(snapshot or snap(), cand or candidate(), mode=mode,
                    preset=preset, grant=grant or a_grant(), now=NOW,
                    now_mono=MONO)


def test_manual_mode_is_off_even_with_a_grant():
    decision = decide(mode="manual", grant=a_grant())
    assert decision.kind == DESLIGADO and not decision.will_execute


def test_assisted_mode_simulates_without_executing():
    decision = decide(mode="assistido", grant=a_grant())
    assert decision.kind == SIMULAR and decision.simulated
    assert not decision.will_execute


def test_automatic_mode_executes_only_when_every_input_agrees():
    decision = decide()
    assert decision.kind == EXECUTAR and decision.will_execute


def test_without_a_grant_automatic_is_refused():
    decision = evaluate(snap(), candidate(), mode="automatico",
                        preset="equilibrado", grant=None, now=NOW, now_mono=MONO)
    assert decision.kind == RECUSAR and "sem grant" in decision.reason


def test_a_preset_cannot_expand_the_grant():
    """Changing preset can change patience, never the action/ceiling set."""
    tiny = a_grant(limits={"bytes": 1})
    for preset in PRESETS:
        decision = decide(preset=preset, grant=tiny)
        assert decision.kind == RECUSAR
        assert "não cobre" in decision.reason


def test_a_preset_cannot_enable_an_action_outside_the_scope():
    plan = a_plan(action="orphan.terminate")
    grant = a_grant(action="orphan.terminate", limits={})
    for preset in PRESETS:
        decision = decide(cand=candidate(plan=plan), preset=preset, grant=grant)
        assert decision.kind == RECUSAR
        assert "escopo automático" in decision.reason


def test_changing_preset_only_changes_eligibility_not_the_grant():
    grant = a_grant()
    conservative = decide(preset="conservador", grant=grant,
                          cand=candidate(sustained_samples=3))
    focus = decide(preset="foco", grant=grant,
                   cand=candidate(sustained_samples=3))

    assert conservative.kind == AGUARDAR
    assert focus.kind == EXECUTAR
    assert grant.limits == {"bytes": 4096}


def test_stale_telemetry_suspends_instead_of_authorizing():
    decision = decide(snapshot=snap(mono=MONO - 30))
    assert decision.kind == SUSPENDER
    assert "antiga" in decision.reason


def test_missing_or_partial_telemetry_suspends():
    partial = (SourceQuality("meminfo", "partial", "contagem limitada",
                             MONO),)
    assert decide(snapshot=snap(sources=partial)).kind == EXECUTAR
    # partial is usable but recorded; missing is not
    missing = (SourceQuality("meminfo", "missing", "", MONO),)
    assert decide(snapshot=snap(sources=missing)).kind == SUSPENDER


def test_reboot_or_resume_requires_revalidation():
    assert decide(cand=candidate(boot_id="boot-b",
                                 last_boot_id="boot-a")).kind == SUSPENDER
    assert decide(cand=candidate(needs_revalidation=True)).kind == SUSPENDER


def test_exhausted_budget_refuses_a_copy():
    decision = decide(cand=candidate(over_budget=True,
                                     budget_reason="sem espaço no destino"))
    assert decision.kind == RECUSAR
    assert "sem espaço" in decision.reason


def test_a_protected_or_unknown_resource_is_preserved():
    assert decide(cand=candidate(protected=True)).kind == RECUSAR
    unknown = decide(cand=candidate(unknown=True))
    assert unknown.kind == RECUSAR and "desconhecido" in unknown.reason


def test_an_unverified_owner_stays_manual():
    decision = decide(cand=candidate(owner_verified=False))
    assert decision.kind == RECUSAR and "permanece manual" in decision.reason


def test_failures_open_the_breaker_and_do_not_escalate():
    decision = decide(cand=candidate(consecutive_failures=2))
    assert decision.kind == SUSPENDER
    assert "disjuntor" in decision.reason and not decision.will_execute


def test_rate_and_interval_limits_wait():
    assert decide(cand=candidate(runs_last_hour=4)).kind == AGUARDAR
    assert decide(cand=candidate(last_run_at=NOW - 30)).kind == AGUARDAR


def test_an_expired_grant_or_plan_refuses_without_replay():
    expired_grant = a_grant(expires_at=NOW - 1)
    assert decide(grant=expired_grant).kind == RECUSAR

    expired_plan = a_plan(created_at=NOW - 100, expires_at=NOW - 1)
    assert decide(cand=candidate(plan=expired_plan)).kind == RECUSAR


def test_an_unknown_preset_or_mode_fails_closed():
    assert decide(preset="inventado").kind == RECUSAR
    assert decide(mode="inventado").kind == RECUSAR
