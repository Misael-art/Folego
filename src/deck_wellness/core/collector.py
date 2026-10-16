"""Assembles one Snapshot per poll. Pure-python, /proc+/sys only.

Hard rule: never stat/open anything under device mounts (/mnt, /run/media...)
here — a dead exFAT card can hang reads in D-state. This module reads fixed
known files and numeric /proc/<pid> entries only.
"""
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import paths
from . import procfs, sysfs, tmpfs as tmpfs_read
from .snapshot import AppRSS, ProcInfo, Snapshot

GROUP_RULES = (
    ("edge", ("msedge", "microsoft-edge")),
    ("chrome", ("chrome", "chromium")),
    ("qoder", ("qoder",)),
    ("codex", ("codex",)),
    ("claude", ("claude",)),
)


def _read_tmpfs(proc_root: str) -> tuple:
    return tmpfs_read.watched_volumes(proc_root=proc_root)


@dataclass
class MetricsCollector:
    proc_root: Path | None = None
    sys_root: Path | None = None
    max_groups: int = 12
    tmpfs_fn: Callable[[str], tuple] | None = None

    def _proc(self) -> Path:
        return Path(self.proc_root) if self.proc_root else Path(paths.proc_root())

    def _sys(self) -> Path:
        return Path(self.sys_root) if self.sys_root else Path(paths.sys_root())

    def collect(self) -> Snapshot:
        root = self._proc()
        errors = []
        mem = procfs.read_meminfo(root)
        if mem is None:
            errors.append("meminfo unavailable")
        pressure_mem = procfs.read_pressure(root, "memory")
        pressure_io = procfs.read_pressure(root, "io")
        pressure_cpu = procfs.read_pressure(root, "cpu")
        load = procfs.read_loadavg(root)
        swaps = procfs.read_swaps(root)
        procs = procfs.list_processes(root)
        # None, não a função, como default: função como default de campo de
        # dataclass vira método ligado e receberia `self` como primeiro argumento
        volumes = (self.tmpfs_fn or _read_tmpfs)(str(root))
        return Snapshot(
            ts=time.time(),
            mem=mem,
            swap_used_kb=sum(s.used_kb for s in swaps),
            swap_total_kb=sum(s.size_kb for s in swaps),
            pressure_memory=pressure_mem,
            pressure_io=pressure_io,
            pressure_cpu=pressure_cpu,
            load=load,
            apps=self._group_rss(procs),
            self_rss_kb=self._self_rss(root),
            procs=tuple(procs),
            tmpfs=volumes,
            errors=tuple(errors),
        )

    def _group_rss(self, procs: list[ProcInfo]) -> tuple[AppRSS, ...]:
        totals: dict[str, list[int]] = {}
        for p in procs:
            g = self._group_for(p)
            acc = totals.setdefault(g, [0, 0])
            acc[0] += p.rss_kb
            acc[1] += 1
        ranked = sorted(totals.items(), key=lambda kv: kv[1][0], reverse=True)
        return tuple(AppRSS(g, rss, n) for g, (rss, n) in ranked[: self.max_groups])

    @staticmethod
    def _group_for(p: ProcInfo) -> str:
        hay = (p.comm + " " + " ".join(p.cmdline[:2])).lower()
        for group, needles in GROUP_RULES:
            if any(n in hay for n in needles):
                return group
        return p.comm or "unknown"

    @staticmethod
    def _self_rss(proc_root: Path) -> int:
        # test seams may not carry 'self'; own process stats come from real /proc
        for candidate in (proc_root / "self", Path("/proc/self")):
            try:
                for line in (candidate / "status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1])
            except OSError:
                continue
        return 0
