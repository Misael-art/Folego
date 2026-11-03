"""Stop one MCP bridge (mcp-remote) chosen by the user, then prove the client still has one.

A bridge is a stateless adapter between a client and an MCP server; the server
is never signalled. This is the one Performance action that uses a signal,
because a bridge has no tray or unit of its own: SIGTERM to the reviewed npm
launcher and node child through `Reaper` (pidfd, identity revalidated, bounded
follow-up). It is manual only, refused for the last connected bridge of a
client, and followed by a fresh scan that reports the client's remaining bridge
and whether the server still answers.
"""
from __future__ import annotations

from dataclasses import asdict

from ...core import mcp_bridges
from ...core.orphans import GroupMember, GroupTarget
from ...core.sessions import read_boot_id
from ...orchestration import ActionPlan, ActionResult, Coordinator, Outcome, ResourceIdentity, perform

ACTION = "performance.bridge-stop"


def plan_for(bridge: mcp_bridges.Bridge, *, boot_id: str) -> ActionPlan:
    return ActionPlan(ACTION, ResourceIdentity("group", f"mcp-bridge:{bridge.pid}", {
        "boot_id": boot_id, "endpoint": bridge.endpoint, "client_pid": bridge.client_pid,
        "members": [{"pid": m.pid, "start_ticks": m.starttime} for m in bridge.members]}),
        {"pid": bridge.pid, "start_ticks": bridge.starttime})


def health(bridges, *, client_pid, endpoint, alive_fn=mcp_bridges.endpoint_alive) -> dict:
    remaining = [b for b in bridges if b.client_pid == client_pid and b.endpoint == endpoint]
    connected = [b for b in remaining if b.connected]
    server = alive_fn(endpoint)
    ok = len(connected) == 1 and server is not False
    text = (f"MCP OK: {len(connected)} ponte conectada ao cliente" if ok else
            f"verificar: {len(connected)} ponte(s) conectada(s) ao cliente")
    text += ("; servidor respondendo" if server else "; servidor sem resposta" if server is False
             else "; servidor remoto não sondado")
    return {"ok": ok, "connected": len(connected), "server": server, "text": text}


def execute(plan: ActionPlan, *, scan, reaper, confirm: bool, coordinator: Coordinator | None = None,
            boot_id_fn=read_boot_id, alive_fn=mcp_bridges.endpoint_alive) -> ActionResult:
    """`scan()` returns the current bridges; it is called at effect time and after."""
    detail = plan.target.to_dict()["detail"]
    if not confirm:
        return ActionResult(ACTION, Outcome.REFUSED, plan.operation_id,
                            "finalizar ponte exige confirmação explícita", plan.target.key)

    def act():
        def refuse(reason):
            return ActionResult(ACTION, Outcome.REFUSED, plan.operation_id, reason, plan.target.key)
        boot = boot_id_fn()
        if not boot or boot != detail.get("boot_id"):
            return refuse("boot desconhecido ou mudou desde a revisão; preservar")
        try:
            bridges = scan()
        except Exception as exc:
            return refuse(f"pontes não reavaliadas: {exc}")
        bridge = next((b for b in bridges if b.pid == plan.params["pid"]), None)
        if bridge is None or bridge.starttime != plan.params["start_ticks"]:
            return refuse("a ponte revisada não existe mais ou mudou de identidade")
        if bridge.endpoint != detail.get("endpoint") or bridge.client_pid != detail.get("client_pid"):
            return refuse("cliente ou endpoint mudou desde a revisão; preservar")
        ok, why = mcp_bridges.stoppable(bridge, bridges)
        if not ok:
            return refuse(why)
        reviewed = {(m["pid"], m["start_ticks"]) for m in detail.get("members", ())}
        members = tuple(GroupMember(m.pid, m.comm, m.rss_kb, m.starttime, m.ppid)
                        for m in bridge.members if (m.pid, m.starttime) in reviewed)
        # Child first: npm exec waits on node, so the launcher follows it out.
        members = tuple(sorted(members, key=lambda m: m.pid != bridge.pid))
        results = reaper.terminate_group(GroupTarget("mcp-bridge", "ponte MCP", members))
        after = health(scan(), client_pid=bridge.client_pid, endpoint=bridge.endpoint, alive_fn=alive_fn)
        effects = {"results": [asdict(r) for r in results], "health": after, "rss_kb": bridge.rss_kb}
        sent = [r for r in results if r.ok]
        if not sent:
            return ActionResult(ACTION, Outcome.REFUSED, plan.operation_id,
                                "; ".join(r.reason or "" for r in results), plan.target.key, effects=effects)
        exited = all(r.exited is True for r in sent) and len(sent) == len(results)
        outcome = Outcome.OK if exited and after["ok"] else Outcome.PARTIAL
        return ActionResult(ACTION, outcome, plan.operation_id,
                            ("ponte finalizada; " if exited else "ponte ainda saindo; ") + after["text"],
                            plan.target.key, effects=effects)

    return perform(coordinator=coordinator or Coordinator(), action=ACTION, target=plan.target,
                   params=dict(plan.params), reviewed_plan=plan, act=act,
                   verdict=lambda result, key: result).verdict
