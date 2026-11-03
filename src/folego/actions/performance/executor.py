"""Performance mode, assisted close: one reviewed group, one confirmed request.

Order is the contract: the plan names the unit, rule, boot and the identities
seen at review; the coordinator writes the intent before anything is touched;
at effect time a fresh observation must show the same boot, the same root
identity, the rule still matching, no agent or exclusion in the group and the
rule in assisted mode. Only then the rule's own closer asks the app to leave,
and the executor follows the reviewed identities for a bounded window. An app
that is still there afterwards is `parcial`, never retried by itself.
"""
from __future__ import annotations

import time
from typing import Callable

from ...core import perf_rules
from ...core.sessions import read_boot_id
from ...orchestration import ActionPlan, ActionResult, Coordinator, Outcome, ResourceIdentity, perform
from . import closers as closer_registry

ACTION = "performance.close"
FOLLOW_S = 20.0
MAX_MEMBERS = 256


MANUAL = "manual"
AUTO = "auto"


def plan_for(suggestion, procs, *, boot_id: str, trigger: str = MANUAL) -> ActionPlan:
    by_pid = {p.pid: p for p in procs}
    members = sorted(({"pid": pid, "start_ticks": by_pid[pid].starttime}
                      for pid in suggestion.pids if pid in by_pid), key=lambda m: m["pid"])
    return ActionPlan(ACTION, ResourceIdentity("group", suggestion.unit, {
        "boot_id": boot_id, "rule": suggestion.rule, "members": members}),
        {"rule": suggestion.rule, "channel": suggestion.channel, "trigger": trigger})


def _refuse(plan, reason):
    return ActionResult(plan.action, Outcome.REFUSED, plan.operation_id, reason, plan.target.key)


def _alive(members, read_proc) -> list[dict]:
    alive = []
    for member in members:
        proc = read_proc(member["pid"])
        if proc is not None and proc.starttime == member["start_ticks"]:
            alive.append(member)
    return alive


def execute(plan: ActionPlan, *, observe: Callable, read_proc: Callable, confirm: bool,
            coordinator: Coordinator | None = None, boot_id_fn=read_boot_id,
            closers=None, follow_s: float = FOLLOW_S, sleep=time.sleep, clock=time.monotonic):
    """`observe()` returns (PerfView, procs, modes) read now; it raises on unreadable policy."""
    closers = closers or closer_registry.CLOSERS
    detail = plan.target.to_dict()["detail"]
    members = list(detail.get("members", ()))
    rule = perf_rules.BY_ID.get(plan.params.get("rule"))
    trigger = plan.params.get("trigger")
    if not confirm:
        return _refuse(plan, "fechamento exige confirmação explícita ou o gatilho automático")
    if (plan.action != ACTION or plan.target.kind != "group" or rule is None
            or set(plan.params) != {"rule", "channel", "trigger"} or trigger not in (MANUAL, AUTO)
            or plan.params["channel"] != rule.channel
            or plan.params["channel"] not in closers or detail.get("rule") != rule.id
            or not 0 < len(members) <= MAX_MEMBERS):
        return _refuse(plan, "plano de desempenho inválido")

    def act():
        boot = boot_id_fn()
        if not boot or boot != detail.get("boot_id"):
            return _refuse(plan, "boot desconhecido ou mudou desde a revisão; preservar")
        try:
            view, procs, modes = observe()
        except Exception as exc:  # unreadable evidence protects the target
            return _refuse(plan, f"observação atual indisponível: {exc}")
        allowed = (perf_rules.AUTOMATIC,) if trigger == AUTO else perf_rules.CLOSING_MODES
        if modes.get(rule.id) not in allowed:
            return _refuse(plan, f"regra {rule.id} não está em modo "
                                 + ("automático" if trigger == AUTO else "assistido"))
        group = next((g for g in view.groups if g.unit == plan.target.key), None)
        if group is None:
            return _refuse(plan, "grupo não encontrado agora; nada a fechar")
        by_pid = {p.pid: p for p in procs}
        root = min(members, key=lambda m: m["start_ticks"])
        current = by_pid.get(root["pid"])
        if current is None or current.starttime != root["start_ticks"] or root["pid"] not in group.pids:
            return _refuse(plan, "identidade do app mudou desde a revisão; preservar")
        ok, why = perf_rules.condition(rule, group, procs)
        if not ok:
            return _refuse(plan, f"condição não vale mais: {why}")
        reviewed = [m for m in members if m["pid"] in group.pids]
        request = closers[plan.params["channel"]](group.pids if rule.channel == "tray" else group.unit)
        if not request.sent:
            return _refuse(plan, request.detail)
        deadline = clock() + follow_s
        alive = _alive(reviewed, read_proc)
        while alive and clock() < deadline:
            sleep(0.5)
            alive = _alive(alive, read_proc)
        effects = {"channel": request.channel, "request": request.detail,
                   "reviewed": len(reviewed), "remaining": len(alive), "rss_kb": group.rss_kb}
        if alive:
            return ActionResult(plan.action, Outcome.PARTIAL, plan.operation_id,
                                f"{request.detail}; {len(alive)} processo(s) ainda vivos após "
                                f"{follow_s:.0f} s; não repetir sem nova revisão",
                                plan.target.key, effects=effects)
        return ActionResult(plan.action, Outcome.OK, plan.operation_id,
                            f"{request.detail}; todos os processos revisados saíram",
                            plan.target.key, effects=effects)

    run = perform(coordinator=coordinator or Coordinator(), action=plan.action, target=plan.target,
                  params=dict(plan.params), reviewed_plan=plan, act=act,
                  verdict=lambda result, key: result)
    return run.verdict
