"""Performance mode, increment 4: when automatic closing may happen. No Qt, no effects.

`decide` is pure. A ready suggestion of a rule in automatic mode is closed only
when every gate holds, in this order: the breaker is closed; the host is under
pressure (memory PSI, low available RAM, or agents in build/test); the item was
not snoozed; the same app was not already closed in this boot (a reopen means
the user wants it, so the rule rests until the next boot); the hourly budget
has room; and the item was announced at least GRACE_S ago. At most one close is
returned per cycle. Two non-successful results in a row open the breaker, which
only an explicit resume closes.

State lives in one small versioned file under a lock; an unreadable or unknown
file raises, and callers treat that as "automatic mode off".
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .agents import BUSY
from .perf_model import PerfView
from .perf_rules import AUTOMATIC

SCHEMA_VERSION = 1
GRACE_S = 60.0
SNOOZE_S = 1800.0
BUDGET_WINDOW_S = 3600.0
BUDGET_TOTAL = 3
BUDGET_PER_RULE = 1
BREAKER_FAILURES = 2
PSI_SOME_AVG60 = 5.0
AVAILABLE_FLOOR = 0.15
HISTORY_KEEP = 50


class AutoStateError(Exception):
    pass


@dataclass
class AutoState:
    history: list = field(default_factory=list)      # {ts, boot, rule, unit, label, outcome}
    announced: dict = field(default_factory=dict)    # key -> first ts
    snoozed: dict = field(default_factory=dict)      # key -> until ts
    failures: int = 0
    breaker: str = ""                                # non-empty reason = open
    last: dict = field(default_factory=dict)         # latest cycle, for display only

    def to_dict(self):
        return {"version": SCHEMA_VERSION, "history": self.history[-HISTORY_KEEP:],
                "announced": self.announced, "snoozed": self.snoozed,
                "failures": self.failures, "breaker": self.breaker, "last": self.last}

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict) or raw.get("version") != SCHEMA_VERSION:
            raise AutoStateError("estado automático com versão não suportada")
        try:
            state = cls(list(raw["history"]), dict(raw["announced"]), dict(raw["snoozed"]),
                        int(raw["failures"]), str(raw["breaker"]), dict(raw.get("last", {})))
        except (KeyError, TypeError, ValueError) as exc:
            raise AutoStateError(f"estado automático inválido: {exc}") from exc
        if any(not isinstance(h, dict) for h in state.history):
            raise AutoStateError("histórico automático inválido")
        return state

    def record(self, *, ts, boot, rule, unit, label, outcome):
        self.history.append({"ts": ts, "boot": boot, "rule": rule, "unit": unit,
                             "label": label, "outcome": outcome})
        self.announced.pop(key_of(rule, unit), None)
        if outcome == "sucesso":
            self.failures = 0
        else:
            self.failures += 1
            if self.failures >= BREAKER_FAILURES:
                self.breaker = (f"{self.failures} fechamentos automáticos sem sucesso seguidos "
                                f"(último: {label}, {outcome})")


class AutoStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = self.path.with_name(self.path.name + ".lock")

    @contextlib.contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self._lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def read(self) -> AutoState:
        if not self.path.exists():
            return AutoState()
        try:
            return AutoState.from_dict(json.loads(self.path.read_text()))
        except (OSError, ValueError) as exc:
            raise AutoStateError(f"estado automático ilegível: {exc}") from exc

    def write(self, state: AutoState) -> None:
        from ..safely.atomicfile import write_atomic
        payload = json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        write_atomic(self.path, payload, mode=0o600)

    @contextlib.contextmanager
    def update(self):
        with self.locked():
            state = self.read()
            yield state
            self.write(state)


def key_of(rule: str, unit: str) -> str:
    return f"{rule}\t{unit}"


def pressure(view: PerfView) -> str:
    """Why the host needs memory now, or "" when it does not."""
    if view.pressure is not None and view.pressure.some_avg60 >= PSI_SOME_AVG60:
        return f"pressão de memória {view.pressure.some_avg60:.1f}% (60 s)"
    if (view.mem_available_kb is not None and view.mem_total_kb
            and view.mem_available_kb < AVAILABLE_FLOOR * view.mem_total_kb):
        return f"RAM disponível abaixo de {AVAILABLE_FLOOR:.0%}"
    if view.activity.load == BUSY:
        return "agentes em build/teste"
    return ""


@dataclass(frozen=True)
class Decision:
    close: object | None            # the Suggestion to close now
    announce: tuple = ()            # Suggestions newly announced this cycle
    waiting: tuple = ()             # (Suggestion, why) kept for display
    trigger: str = ""


def decide(suggestions, view: PerfView, state: AutoState, *, now: float, boot: str) -> Decision:
    """Mutates only `state.announced` (and forgets stale entries); never acts."""
    autos = [s for s in suggestions if s.kind == "close" and s.mode == AUTOMATIC and s.channel]
    live = {key_of(s.rule, s.unit) for s in autos if s.ready}
    for key in [k for k in state.announced if k not in live]:
        del state.announced[key]
    for key in [k for k, until in state.snoozed.items() if until <= now]:
        del state.snoozed[key]
    trigger = pressure(view)
    recent = [h for h in state.history if now - float(h.get("ts", 0)) < BUDGET_WINDOW_S]
    announce, waiting, chosen = [], [], None
    for item in autos:
        key = key_of(item.rule, item.unit)
        if not item.ready:
            waiting.append((item, f"observando {item.waited_s:.0f}/{item.need_s:.0f} s"))
            continue
        if state.breaker:
            waiting.append((item, "disjuntor aberto: " + state.breaker))
            continue
        if key in state.snoozed:
            waiting.append((item, "adiado pelo usuário"))
            continue
        if any(h.get("boot") == boot and h.get("rule") == item.rule and h.get("label") == item.label
               and h.get("outcome") == "sucesso" for h in state.history):
            waiting.append((item, "já fechado neste boot; reaberto pelo usuário, regra em repouso"))
            continue
        if not trigger:
            waiting.append((item, "sem pressão no host; só sugerido"))
            continue
        if len(recent) >= BUDGET_TOTAL or sum(h.get("rule") == item.rule for h in recent) >= BUDGET_PER_RULE:
            waiting.append((item, "orçamento por hora esgotado"))
            continue
        if key not in state.announced:
            state.announced[key] = now
            announce.append(item)
            waiting.append((item, f"aviso enviado; fecha em {GRACE_S:.0f} s"))
            continue
        left = GRACE_S - (now - float(state.announced[key]))
        if left > 0 or chosen is not None:
            waiting.append((item, f"carência: {max(left, 0):.0f} s"))
            continue
        chosen = item
    return Decision(chosen, tuple(announce), tuple(waiting), trigger)
