"""Performance mode, observation layer: processes grouped per app. No Qt, no effects.

A group is the leaf systemd unit/scope of the user session, because that is how
the desktop launched the app and how it can later be stopped as a whole. Only
`app-*` units of the user's own app slice can ever become candidates; every
session, system or unidentified group is protected by class, and so is any
group hosting agent work (see `core.agents`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .agents import AgentActivity
from .snapshot import Pressure, ProcInfo, Snapshot

AGENT = "agent"
PROTECTED = "protected"
OBSERVED = "observed"

# Apps that are part of the working environment even when launched as `app-*`.
PROTECTED_LABELS = {
    "folego": "o próprio Fôlego",
    "jdsp": "áudio",
    "jamesdsp": "áudio",
    "pipewire": "áudio",
    "phasezero": "infraestrutura PhaseZero",
    "hermes": "daemon de agente",
    "ai-memory": "daemon de agente",
    "org.kde": "sessão KDE",
    "kdeconnect": "sessão KDE",
    "geoclue": "localização",
}
_INSTANCE = re.compile(r"[@-][0-9a-f]{8,}$|-\d+$|@autostart$|@\d+$")


@dataclass(frozen=True)
class AppGroup:
    unit: str
    label: str
    pids: tuple[int, ...]
    rss_kb: int
    cpu_frac: float | None
    state: str
    reason: str
    # True only when the sole protection is the group's class (session service or
    # fixed label); an explicit rule may name such a unit. Agents and user
    # exclusions are never overridable.
    class_only: bool = False

    @property
    def procs(self) -> int:
        return len(self.pids)


@dataclass(frozen=True)
class PerfView:
    groups: tuple[AppGroup, ...]
    activity: AgentActivity
    pressure: Pressure | None
    mem_available_kb: int | None
    mem_total_kb: int | None
    # unit -> why someone is using it now (focus, audio, download, project file);
    # only probed for groups that could become candidates.
    in_use: dict = field(default_factory=dict)

    def reclaimable_kb(self) -> int:
        return sum(g.rss_kb for g in self.groups if g.state == OBSERVED)


def leaf_unit(cgroup: str | None) -> str | None:
    if not cgroup:
        return None
    leaf = cgroup.rstrip("/").rsplit("/", 1)[-1]
    return leaf if leaf.endswith((".service", ".scope")) else None


def unit_label(unit: str) -> str:
    name = unit.rsplit(".", 1)[0]
    if name.startswith("app-"):
        name = name[4:]
    name = name.replace("\\x2d", "-")
    return _INSTANCE.sub("", name) or name


def _protection(unit: str | None, label: str) -> str | None:
    if unit is None:
        return "grupo não identificado"
    if not unit.startswith("app-"):
        return "serviço da sessão"
    for key, reason in PROTECTED_LABELS.items():
        if label.startswith(key):
            return reason
    return None


def build(snapshot: Snapshot, activity: AgentActivity, *,
          cgroup_fn: Callable[[int], str | None], uid: int | None = None,
          protected_fn: Callable[[ProcInfo], str | None] | None = None) -> PerfView:
    buckets: dict[str | None, list[ProcInfo]] = {}
    for proc in snapshot.procs:
        if uid is not None and proc.uid != uid:
            continue
        buckets.setdefault(leaf_unit(cgroup_fn(proc.pid)), []).append(proc)
    groups = []
    for unit, members in buckets.items():
        label = unit_label(unit) if unit else "?"
        agent = [p.pid for p in members if activity.protects(p.pid)]
        user = next((r for r in map(protected_fn, members) if r), None) if protected_fn else None
        reason = _protection(unit, label)
        class_only = False
        if agent:
            state, reason = AGENT, "hospeda trabalho de agente"
        elif user:
            state, reason = PROTECTED, user
        elif reason:
            state, class_only = PROTECTED, unit is not None
        else:
            state, reason = OBSERVED, "sem agente; elegível para regras"
        # Percent of one CPU; a member first seen in this sample has no delta yet.
        fractions = [p.cpu_frac for p in members if p.cpu_frac is not None]
        groups.append(AppGroup(
            unit or "?", label, tuple(sorted(p.pid for p in members)),
            sum(p.rss_kb for p in members),
            sum(fractions) if fractions else None,
            state, reason, class_only))
    groups.sort(key=lambda g: g.rss_kb, reverse=True)
    mem = snapshot.mem
    return PerfView(tuple(groups), activity, snapshot.pressure_memory,
                    mem.mem_available_kb if mem else None, mem.mem_total_kb if mem else None)



def cwd_of(pid: int, proc_root: str | None = None) -> str | None:
    import os
    from .. import paths
    try:
        return os.readlink(f"{proc_root or paths.proc_root()}/{pid}/cwd")
    except OSError:
        return None  # unreadable cwd is "unknown", which never removes a protection


def observe(snapshot: Snapshot, *, proc_root: str | None = None, uid: int | None = None,
            git_cache: dict | None = None, protected_fn=None, probe_fn=None) -> PerfView:
    """Host observation over an already collected snapshot (CPU needs a prior sample)."""
    import os
    from dataclasses import replace
    from . import agents, usage
    from .. import paths
    from .sessions import read_cgroup
    activity = agents.detect(snapshot.procs, cwd_fn=lambda pid: cwd_of(pid, proc_root),
                             git_cache=git_cache)
    view = build(snapshot, activity, cgroup_fn=lambda pid: read_cgroup(pid, proc_root),
                 uid=os.getuid() if uid is None else uid, protected_fn=protected_fn)
    candidates = [g for g in view.groups
                  if g.state == OBSERVED or (g.state == PROTECTED and g.class_only)]
    if not candidates:
        return view
    probes = (probe_fn or usage.probe)()
    root = proc_root or paths.proc_root()
    in_use = {}
    for group in candidates:
        reason = usage.in_use(group.pids, probes=probes, projects=activity.projects, proc_root=root)
        if reason:
            in_use[group.unit] = reason
    return replace(view, in_use=in_use)
