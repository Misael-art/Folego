"""M4 core: which processes may be offered for termination. Pure over snapshots.

Two independent surfaces:
* proven orphans — reparented to PID 1, no live children, not a leader, and
  observed with frozen CPU for a while. Offered one by one.
* browser groups (Edge/Chrome) — the whole process family, offered as a unit
  for a large, predictable yield. Leader/child rules do not apply here because
  a browser cannot be closed without its leader; the strong pre-list does.

No /proc access and no Qt: the collector already puts ProcInfo in the snapshot.

Known limit, on purpose: five minutes without CPU does not prove abandonment for
a windowed application that is merely idle (an MT5 terminal with the markets
closed looks exactly like a leftover). The row shows the adopter and the command
so the human decides — the app never infers "useless" from quiet.
"""
import os
from dataclasses import dataclass

from .collector import GROUP_RULES
from .snapshot import ProcInfo, Snapshot

MIN_IDLE_S = 300.0

# Named by prefix, lowercase. Anything here is never offered, in either mode.
PROTECTED_PREFIXES = (
    "systemd", "init", "plasmashell", "plasma_session", "kwin", "kdeinit",
    "pipewire", "wireplumber", "rtkit", "dbuspolicy", "dbus-daemon",
    "dbus-broker", "xdg-dbus-proxy", "xdg-document", "xdg-permission",
    "bwrap", "chrome_crashpad", "edge_crashpad", "crashpad", "xsettingsd",
    "polkit", "xwayland", "wayland", "sddm", "sshd", "cron", "akonadi",
    "gpg-agent", "ssh-agent", "konsole", "yakuake", "dolphin",
    "yad", "folego", "notify", "gvfsd", "kscreen", "kglobalaccels",
    "ksecretd", "kwallet", "kded",
)

KILLABLE_GROUPS = ("edge", "chrome")
GROUP_LABELS = {"edge": "Microsoft Edge", "chrome": "Google Chrome/Chromium"}

# A browser attached to a driver is a tool's worker, not idle RAM: SIGTERM-ing it
# breaks a session the user cannot see, and no flag inside it says whose.
AUTOMATION_MARKERS = ("--remote-debugging-pipe", "--remote-debugging-port")

# Binaries that are automation infrastructure rather than the user's browser
# window. Observed on the Deck on 2026-10-14: 18 of 21 processes in the "Chrome
# family" belonged to agent tooling, one per running agent.
TOOLING_EXE_MARKERS = ("chrome-headless-shell", "ms-playwright", "devtools-mcp")


@dataclass(frozen=True)
class OrphanCandidate:
    pid: int
    comm: str
    state: str
    uid: int
    rss_kb: int
    swap_kb: int
    starttime: int
    idle_s: float
    ppid: int = 1
    cmdline: tuple[str, ...] = ()
    cpu_frac: float | None = None
    # CPU ativa não é a regra antiga de ociosidade: a linha é uma investigação,
    # não uma prova de abandono. A UI não oferece ação automática para ela.
    investigation: bool = False
    cpu_ticks: int | None = None

    @property
    def label(self) -> str:
        return self.comm or f"pid {self.pid}"


@dataclass(frozen=True)
class GroupMember:
    pid: int
    comm: str
    rss_kb: int
    starttime: int
    ppid: int


@dataclass(frozen=True)
class GroupTarget:
    group: str
    label: str
    members: tuple[GroupMember, ...]

    @property
    def total_rss_kb(self) -> int:
        return sum(m.rss_kb for m in self.members)


def is_protected(proc: ProcInfo, *, self_pid: int | None = None,
                 ancestor_pids: frozenset[int] = frozenset()) -> bool:
    if self_pid is not None and proc.pid == self_pid:
        return True
    if proc.pid in ancestor_pids:
        return True
    comm = proc.comm.lower()
    return any(comm.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def ancestor_pids(procs, self_pid: int) -> frozenset[int]:
    """Parent chain of self_pid inside the observed set — our own tree is off-limits."""
    by_pid = {p.pid: p for p in procs}
    chain: set[int] = set()
    current = by_pid.get(self_pid)
    while current is not None and current.ppid in by_pid and current.ppid not in chain:
        chain.add(current.ppid)
        current = by_pid[current.ppid]
    chain.add(self_pid)
    return frozenset(chain)


def executable_of(proc: ProcInfo) -> str:
    """First blank-separated token of argv[0].

    /proc/<pid>/comm is only a 15-character label and Chrome-family helpers stuff
    their whole command line into argv[0], so neither may decide what a process
    is: on the Deck an npm worker labelled itself "chrome" and a Playwright shell
    carried msEdgeUpdate* flags. The executable path is what survives that.
    """
    return proc.cmdline[0].split()[0] if proc.cmdline else ""


def _matches_group(proc: ProcInfo, needles) -> bool:
    exe = executable_of(proc).lower()
    return bool(exe) and any(needle in exe for needle in needles)


def under_automation_control(proc: ProcInfo) -> bool:
    line = " ".join(proc.cmdline).lower()
    return any(marker in line for marker in AUTOMATION_MARKERS)


def is_tooling(proc: ProcInfo) -> bool:
    exe = executable_of(proc).lower()
    return any(marker in exe for marker in TOOLING_EXE_MARKERS)


def _protection_reason(protected_fn, proc: ProcInfo) -> str | None:
    if protected_fn is None:
        return None
    try:
        return protected_fn(proc)
    except Exception as exc:  # fail closed: an unreadable protection file protects
        return f"proteção ilegível: {type(exc).__name__}: {exc}"


def group_targets(procs, *, groups=KILLABLE_GROUPS, uid: int | None = None,
                  self_pid: int | None = None,
                  protected_fn=None) -> tuple[GroupTarget, ...]:
    own_uid = os.getuid() if uid is None else uid
    me = os.getpid() if self_pid is None else self_pid
    protected = ancestor_pids(procs, me)
    rules = dict(GROUP_RULES)
    pool = [p for p in procs
            if p.uid == own_uid and not is_tooling(p) and not under_automation_control(p)]
    out = []
    for group in groups:
        family = [
            p for p in pool
            if _matches_group(p, rules[group])
            and not is_protected(p, self_pid=me, ancestor_pids=protected)
        ]
        # Uma família é a unidade: se qualquer membro estiver protegido (sessão
        # com "manter ativo", exclusão do usuário ou arquivo ilegível), não se
        # oferece um encerramento parcial que mataria o pai e deixaria o filho.
        if any(_protection_reason(protected_fn, p) for p in family):
            continue
        members = [GroupMember(p.pid, p.comm, p.rss_kb, p.starttime, p.ppid)
                   for p in family]
        pool = [p for p in pool if p.pid not in {m.pid for m in members}]
        if members:
            # children first: a live parent respawns a killed child
            members.sort(key=lambda m: m.pid, reverse=True)
            out.append(GroupTarget(group, GROUP_LABELS[group], tuple(members)))
    return tuple(out)


def is_adopted(proc: ProcInfo, parent: ProcInfo | None) -> bool:
    """Whether the process now sits under a supervisor instead of its own launcher.

    PID 1 is the textbook case. This desktop also runs systemd --user as a child
    subreaper — measured on the Deck: leftovers are adopted by the user manager
    and never reach PID 1 — so adoption is read from the session instead: an
    adopted process still carries its dead launcher's session, while a process
    started by its current parent shares that parent's session.
    """
    if proc.ppid == 1:
        return True
    if parent is None or parent.session != parent.pid:
        return False
    return proc.session != parent.session


@dataclass
class _Observation:
    cpu: int
    last_change_ts: float


class OrphanTracker:
    """Stateful across polls: idleness is measured between observations, never assumed."""

    def __init__(self, *, min_idle_s: float = MIN_IDLE_S, uid: int | None = None,
                 self_pid: int | None = None, protected_fn=None):
        self.min_idle_s = min_idle_s
        self.uid = uid
        self.self_pid = self_pid
        self.protected_fn = protected_fn
        self._seen: dict[tuple[int, int], _Observation] = {}

    def observe(self, snapshot: Snapshot) -> tuple[OrphanCandidate, ...]:
        # Amostra real sem processos utilizáveis não prova "nenhum órfão": uma
        # varredura que falhou não pode alimentar a lista. Snapshots sintéticos
        # (sem fontes declaradas) continuam aceitos pelos testes de unidade.
        if snapshot.sources and not snapshot.usable("processes"):
            return ()
        own_uid = os.getuid() if self.uid is None else self.uid
        me = os.getpid() if self.self_pid is None else self.self_pid
        procs = snapshot.procs
        # Idade da CPU é intervalo: relógio monotônico quando existir; parede é
        # só o fallback de snapshots antigos/sintéticos.
        now = snapshot.mono if snapshot.mono > 0 else snapshot.ts
        protected = ancestor_pids(procs, me)
        by_pid = {p.pid: p for p in procs}
        parents: dict[int, int] = {}
        for p in procs:
            if p.state != "Z":
                parents[p.ppid] = parents.get(p.ppid, 0) + 1
        keys = {(p.pid, p.starttime) for p in procs}
        self._seen = {k: v for k, v in self._seen.items() if k in keys}

        candidates = []
        for p in procs:
            reason = _protection_reason(self.protected_fn, p)
            if reason:
                # Não conta o tempo em que esteve protegido: se a proteção sair,
                # a observação de ociosidade recomeça em vez de herdar o passado.
                self._seen.pop((p.pid, p.starttime), None)
                continue
            cpu = p.utime + p.stime
            key = (p.pid, p.starttime)
            previous = self._seen.get(key)
            if previous is None or previous.cpu != cpu:
                self._seen[key] = _Observation(cpu, now)
            if not self._qualifies(p, own_uid=own_uid, parents=parents,
                                   protected=protected, by_pid=by_pid):
                continue
            idle_s = now - self._seen[key].last_change_ts
            if idle_s >= self.min_idle_s:
                candidates.append(OrphanCandidate(
                    pid=p.pid, comm=p.comm, state=p.state, uid=p.uid,
                    rss_kb=p.rss_kb, swap_kb=p.swap_kb, starttime=p.starttime,
                    idle_s=idle_s, ppid=p.ppid, cmdline=p.cmdline,
                    cpu_frac=p.cpu_frac, cpu_ticks=p.utime + p.stime))
        return tuple(sorted(candidates, key=lambda c: -c.rss_kb))

    @staticmethod
    def _qualifies(p: ProcInfo, *, own_uid: int, parents: dict[int, int],
                   protected: frozenset[int], by_pid: dict[int, ProcInfo]) -> bool:
        return (p.uid == own_uid and p.state != "Z"
                and p.pid != p.pgrp and p.pid != p.session
                and is_adopted(p, by_pid.get(p.ppid))
                and parents.get(p.pid, 0) == 0
                and not is_protected(p, ancestor_pids=protected))


def active_investigation(snapshot: Snapshot, *, min_cpu_frac: float = 10.0,
                         uid: int | None = None, self_pid: int | None = None,
                         protected_fn=None) -> tuple[OrphanCandidate, ...]:
    """Adopted, childless processes with active CPU: investigation, not proof.

    The old orphan rule requires a frozen CPU counter, so a runaway leftover that
    keeps consuming CPU never appears there. This surface lists it as something
    to inspect, but deliberately does not claim abandonment and offers no
    automatic action: a useful build can also be CPU-active.
    """
    if snapshot.sources and not snapshot.usable("processes"):
        return ()
    own_uid = os.getuid() if uid is None else uid
    me = os.getpid() if self_pid is None else self_pid
    procs = snapshot.procs
    protected = ancestor_pids(procs, me)
    by_pid = {p.pid: p for p in procs}
    parents: dict[int, int] = {}
    for p in procs:
        if p.state != "Z":
            parents[p.ppid] = parents.get(p.ppid, 0) + 1
    minimum = max(0.0, float(min_cpu_frac))
    out = []
    for p in procs:
        if p.cpu_frac is None or p.cpu_frac < minimum:
            continue
        if not OrphanTracker._qualifies(p, own_uid=own_uid, parents=parents,
                                        protected=protected, by_pid=by_pid):
            continue
        if _protection_reason(protected_fn, p):
            continue
        out.append(OrphanCandidate(
            pid=p.pid, comm=p.comm, state=p.state, uid=p.uid,
            rss_kb=p.rss_kb, swap_kb=p.swap_kb, starttime=p.starttime,
            idle_s=0.0, ppid=p.ppid, cmdline=p.cmdline,
            cpu_frac=p.cpu_frac, investigation=True))
    return tuple(sorted(out, key=lambda c: (-(c.cpu_frac or 0.0), -c.rss_kb)))
