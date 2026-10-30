"""Manual process batches under the common coordinator, with stable boot IDs."""
from dataclasses import asdict, dataclass
from types import SimpleNamespace

from ...core.sessions import read_boot_id
from ...core.orphans import GroupTarget, KILLABLE_GROUPS
from ...orchestration import ActionPlan, ActionResult, Coordinator, Coordinated, Outcome, ResourceIdentity, perform


@dataclass(frozen=True)
class BatchResult:
    results: tuple = ()


def plan_for(targets, *, boot_id, force=False, require_orphan=True, group=""):
    members = [{"pid": t.pid, "starttime": t.starttime, "comm": t.comm,
                "ppid": getattr(t, "ppid", 0), "rss_kb": getattr(t, "rss_kb", 0),
                "cpu_ticks": getattr(t, "cpu_ticks", None)} for t in targets]
    return ActionPlan("process.signal", ResourceIdentity("group", "process.selection", {
        "boot_id": boot_id, "members": [{"pid": m["pid"], "start_ticks": m["starttime"]} for m in members]}),
        {"members": members, "signal": 9 if force else 15,
         "require_orphan": require_orphan, "group": group})


def execute(plan, *, reaper, coordinator=None, boot_id_fn=read_boot_id,
            confirm=False, force_confirm=False):
    members = plan.params.get("members", ())
    reason = ""
    if not isinstance(members, (tuple, list)):
        members = ()
        reason = "membros precisam ser lista"
    if not confirm or plan.params.get("signal") == 9 and not force_confirm:
        reason = "sinal exige confirmação; SIGKILL exige confirmação separada"
    if (plan.action != "process.signal" or plan.target.kind != "group"
            or set(plan.params) != {"members", "signal", "require_orphan", "group"}
            or not 0 < len(members) <= 64 or type(plan.params.get("signal")) is not int
            or plan.params.get("signal") not in (9, 15)
            or type(plan.params.get("require_orphan")) is not bool):
        reason = "plano de processos inválido ou acima do limite de 64 alvos"
    targets = []
    try:
        for member in members:
            if (set(member) != {"pid", "starttime", "comm", "ppid", "rss_kb", "cpu_ticks"}
                    or type(member["pid"]) is not int or member["pid"] <= 1
                    or type(member["starttime"]) is not int or member["starttime"] <= 0
                    or not isinstance(member["comm"], str)):
                reason = "identidade de processo incompleta"
            if plan.params["require_orphan"] and (type(member.get("cpu_ticks")) is not int
                                                   or member["cpu_ticks"] < 0):
                reason = "evidência de CPU ausente; reanalise antes de sinalizar"
            targets.append(SimpleNamespace(**member))
        expected = [{"pid": t.pid, "start_ticks": t.starttime} for t in targets]
        if len({t.pid for t in targets}) != len(targets):
            reason = "PID repetido no plano"
        if list(plan.target.to_dict()["detail"].get("members", ())) != expected:
            reason = "seleção difere das identidades revisadas"
    except (TypeError, KeyError, AttributeError):
        reason = "membros de processo ilegíveis"
    if not plan.params.get("require_orphan") and plan.params.get("group") not in KILLABLE_GROUPS:
        reason = "grupo manual não reconhecido"
    if reason:
        return Coordinated(None, ActionResult(plan.action, Outcome.REFUSED, plan.operation_id,
                                              reason, plan.target.key))
    box = {}

    def act(approved):
        boot = boot_id_fn()
        if not boot or boot != approved.target.detail.get("boot_id"):
            return ActionResult(plan.action, Outcome.REFUSED, plan.operation_id,
                                "boot desconhecido ou mudou desde a análise; preservar", plan.target.key)
        if not approved.params["require_orphan"]:
            from ...core import procfs
            from ...core.orphans import group_targets
            from ... import paths
            from pathlib import Path
            root = Path(getattr(reaper, "proc_root", paths.proc_root()))
            scanned = [procfs.read_proc(root, target.pid) for target in targets]
            if any(member is None for member in scanned):
                return ActionResult(plan.action, Outcome.REFUSED, plan.operation_id,
                                    "grupo não revalidado: processos incompletos", plan.target.key)
            groups = group_targets(scanned, groups=(approved.params["group"],),
                                   protected_fn=getattr(reaper, "protected_fn", None))
            eligible = {(m.pid, m.starttime) for g in groups for m in g.members}
            if any((t.pid, t.starttime) not in eligible for t in targets):
                return ActionResult(plan.action, Outcome.REFUSED, plan.operation_id,
                                    "grupo mudou ou contém alvo protegido; preservar", plan.target.key)
        if plan.params["signal"] == 9:
            if hasattr(reaper, "force_many"):
                results = tuple(reaper.force_many(targets, confirm=True,
                                require_orphan=plan.params["require_orphan"]))
            else:
                results = tuple(reaper.force(t, confirm=True, require_orphan=plan.params["require_orphan"])
                                for t in targets)
        elif not plan.params["require_orphan"]:
            group = GroupTarget(plan.params["group"], plan.params["group"], tuple(targets))
            results = tuple(reaper.terminate_group(group))
        elif hasattr(reaper, "terminate_many"):
            results = tuple(reaper.terminate_many(targets))
        else:
            results = tuple(reaper.terminate(t) for t in targets)
        box["result"] = BatchResult(results)
        sent = [r for r in results if r.ok]
        if not sent:
            outcome = Outcome.REFUSED
        elif len(sent) < len(results) or any(r.exited is not True for r in sent):
            outcome = Outcome.PARTIAL
        else:
            outcome = Outcome.OK
        return ActionResult(plan.action, outcome, plan.operation_id,
                            "sinais observados; ausência de acompanhamento não comprova término",
                            plan.target.key, effects={"results": [asdict(r) for r in results]})

    run = perform(coordinator=coordinator or Coordinator(), action=plan.action,
                  target=plan.target, params=dict(plan.params), reviewed_plan=plan,
                  act=lambda: act(plan), verdict=lambda result, key: result)
    return Coordinated(box.get("result"), run.verdict)
