"""Performance mode, increment 2: target rules, user modes and suggestions. No Qt, no effects.

Rules are built in and allow-list only: a group becomes a suggestion only when
an explicit rule names it and its objective condition held for the whole wait.
The user file only chooses a mode per rule. A missing file means the defaults;
an unreadable file or an unknown schema disables every rule (fail closed).
Assisted and automatic modes do not exist yet and are refused as values.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .perf_model import OBSERVED, PROTECTED, PerfView
from .snapshot import ProcInfo

SCHEMA_VERSION = 1
OFF = "off"
SUGGEST = "suggest"
MODES = (OFF, SUGGEST)
CLOSE = "close"
ADVICE = "advice"


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    kind: str
    labels: tuple[str, ...] = ()
    units: tuple[str, ...] = ()       # exact units; may name class-protected services
    idle_cpu: float = 10.0            # percent of one CPU, summed over the group
    idle_s: float = 600.0
    busy_markers: tuple[str, ...] = ()  # any member cmdline fragment means "in use"
    closer: str = ""
    default: str = SUGGEST


RULES = (
    Rule("steam-idle", "Steam aberto sem jogo", CLOSE, labels=("steam",), idle_cpu=15.0,
         idle_s=600.0, busy_markers=("SteamLaunch", "proton", "wine", "reaper"),
         closer="Sair pela bandeja do Steam"),
    Rule("edge-after-login", "Edge ocioso, sem agente", CLOSE,
         labels=("microsoft-edge", "com.microsoft.Edge"), idle_cpu=10.0, idle_s=900.0,
         closer="Fechar as janelas do Edge (as abas são preservadas)"),
    Rule("autostart-extras", "Inicialização dispensável", CLOSE, idle_cpu=5.0, idle_s=120.0,
         units=("biglinux-welcome.service", "appimagelauncherd.service",
                "app-geoclue\\x2ddemo\\x2dagent@autostart.service",
                "app-pamac\\x2dtray\\x2dplasma@autostart.service"),
         closer="Parar a unit de usuário e tirar do início da sessão"),
    Rule("mcp-duplicate", "Ponte MCP duplicada", ADVICE, idle_s=60.0,
         closer="Fixar a versão do mcp-remote e reiniciar o cliente que duplicou"),
    Rule("electron-bloat", "Processo de app acima de 1,5 GB", ADVICE, idle_s=1800.0,
         closer="Reiniciar o app quando for conveniente"),
)
BY_ID = {rule.id: rule for rule in RULES}
BLOAT_KB = int(1.5 * 1024 * 1024)


class PolicyError(Exception):
    pass


def load_modes(path: Path) -> dict[str, str]:
    """Mode per rule; raises PolicyError so callers can disable the whole mode."""
    modes = {rule.id: rule.default for rule in RULES}
    if not path.exists():
        return modes
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise PolicyError(f"regras de desempenho ilegíveis: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != SCHEMA_VERSION:
        raise PolicyError("versão das regras de desempenho não suportada: "
                          f"{raw.get('version') if isinstance(raw, dict) else raw!r}")
    chosen = raw.get("modes", {})
    if not isinstance(chosen, dict):
        raise PolicyError("campo modes inválido")
    for rule_id, mode in chosen.items():
        if rule_id not in BY_ID:
            raise PolicyError(f"regra desconhecida: {rule_id}")
        if mode not in MODES:
            raise PolicyError(f"modo não suportado para {rule_id}: {mode!r}")
        modes[rule_id] = mode
    return modes


def save_modes(path: Path, modes: dict[str, str]) -> None:
    from ..safely.atomicfile import write_atomic
    for rule_id, mode in modes.items():
        if rule_id not in BY_ID or mode not in MODES:
            raise PolicyError(f"modo inválido: {rule_id}={mode!r}")
    payload = json.dumps({"version": SCHEMA_VERSION, "modes": modes},
                         ensure_ascii=False, sort_keys=True).encode("utf-8")
    write_atomic(path, payload, mode=0o600)


@dataclass(frozen=True)
class Suggestion:
    rule: str
    title: str
    kind: str
    unit: str
    label: str
    rss_kb: int
    reason: str
    action: str
    ready: bool
    waited_s: float
    need_s: float


class ConditionTracker:
    """Since when a condition has held for one identity; any gap restarts it."""

    def __init__(self):
        self._since: dict[tuple, float] = {}

    def held(self, key: tuple, ok: bool, now: float, seen: set) -> float:
        seen.add(key)
        if not ok:
            self._since.pop(key, None)
            return 0.0
        return now - self._since.setdefault(key, now)

    def forget_unseen(self, seen: set) -> None:
        for key in [k for k in self._since if k not in seen]:
            del self._since[key]


def _matches(rule: Rule, group) -> bool:
    if group.unit in rule.units:
        return group.state == OBSERVED or (group.state == PROTECTED and group.class_only)
    if group.state != OBSERVED:
        return False
    return any(group.label.startswith(prefix) for prefix in rule.labels)


def plan(view: PerfView, procs: tuple[ProcInfo, ...], modes: dict[str, str],
         tracker: ConditionTracker, now: float) -> tuple[Suggestion, ...]:
    by_pid = {p.pid: p for p in procs}
    seen: set = set()
    out: list[Suggestion] = []

    def add(rule, group_unit, label, rss, reason, key, ok):
        waited = tracker.held(key, ok, now, seen)
        if ok:
            out.append(Suggestion(rule.id, rule.title, rule.kind, group_unit, label, rss, reason,
                                  rule.closer, waited >= rule.idle_s, waited, rule.idle_s))

    for group in view.groups:
        members = [by_pid[pid] for pid in group.pids if pid in by_pid]
        identity = min((p.starttime for p in members), default=0)
        for rule in RULES:
            if rule.kind != CLOSE or modes.get(rule.id) == OFF or not _matches(rule, group):
                continue
            busy = next((m for m in rule.busy_markers
                         if any(m in " ".join(p.cmdline) for p in members)), None)
            quiet = group.cpu_frac is not None and group.cpu_frac < rule.idle_cpu
            reason = (f"em uso ({busy})" if busy else
                      f"CPU {group.cpu_frac:.0f}% < {rule.idle_cpu:.0f}%" if quiet else
                      "CPU sem medida" if group.cpu_frac is None else "ativo")
            ok = quiet and not busy
            add(rule, group.unit, group.label, group.rss_kb, reason, (rule.id, group.unit, identity), ok)

    if modes.get("mcp-duplicate") != OFF:
        rule = BY_ID["mcp-duplicate"]
        bridges: dict[tuple, list[ProcInfo]] = {}
        for p in procs:
            # Only the npm launcher title carries package and endpoint; its node child
            # and wrapper processes would count the same bridge twice.
            if p.cmdline and p.cmdline[0].startswith("npm") and "mcp-remote" in " ".join(p.cmdline):
                bridges.setdefault(p.cmdline, []).append(p)
        for cmd, copies in bridges.items():
            if len(copies) > 1:
                rss = sum(p.rss_kb for p in copies)
                add(rule, " ".join(cmd)[:80], "mcp-remote", rss,
                    f"{len(copies)} cópias do mesmo comando e endpoint", (rule.id, cmd), True)

    if modes.get("electron-bloat") != OFF:
        rule = BY_ID["electron-bloat"]
        for p in procs:
            if p.rss_kb >= BLOAT_KB:
                add(rule, f"pid {p.pid}", p.comm, p.rss_kb, "um único processo acima de 1,5 GB",
                    (rule.id, p.pid, p.starttime), True)

    tracker.forget_unseen(seen)
    out.sort(key=lambda s: (not s.ready, -s.rss_kb))
    return tuple(out)
