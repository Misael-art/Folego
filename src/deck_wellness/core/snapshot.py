"""Pure data containers for one metrics sample. No logic, no Qt."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MemInfo:
    mem_total_kb: int
    mem_available_kb: int


@dataclass(frozen=True)
class Pressure:
    some_avg10: float
    some_avg60: float
    some_avg300: float
    some_total: int


@dataclass(frozen=True)
class LoadAvg:
    one: float
    five: float
    fifteen: float
    runnable: int
    total: int


@dataclass(frozen=True)
class SwapInfo:
    name: str
    type: str
    size_kb: int
    used_kb: int
    priority: int


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    comm: str
    state: str
    ppid: int
    pgrp: int
    session: int
    utime: int
    stime: int
    starttime: int
    rss_kb: int
    swap_kb: int
    uid: int
    cmdline: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppRSS:
    group: str
    rss_kb: int
    procs: int


@dataclass(frozen=True)
class Snapshot:
    ts: float
    mem: MemInfo | None
    swap_used_kb: int
    swap_total_kb: int
    pressure_memory: Pressure | None
    pressure_io: Pressure | None
    pressure_cpu: Pressure | None
    load: LoadAvg | None
    apps: tuple[AppRSS, ...]
    self_rss_kb: int
    procs: tuple[ProcInfo, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)
