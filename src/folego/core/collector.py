"""Assembles one Snapshot per poll. Pure-python, /proc+/sys only.

Hard rule: never stat/open anything under device mounts (/mnt, /run/media...)
here — a dead exFAT card can hang reads in D-state. This module reads fixed
known files and numeric /proc/<pid> entries only.
"""
import os
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from .. import paths
from . import procfs, sysfs, tmpfs as tmpfs_read
from .snapshot import (AppRSS, CpuTimes, ERROR, MISSING, OK, PARTIAL,
                       ProcInfo, Snapshot, SourceQuality)


def _clock_ticks() -> int:
    try:
        return int(os.sysconf("SC_CLK_TCK"))
    except (AttributeError, OSError, ValueError):
        return 100

GROUP_RULES = (
    ("edge", ("msedge", "microsoft-edge")),
    ("chrome", ("chrome", "chromium")),
    ("qoder", ("qoder",)),
    ("codex", ("codex",)),
    ("claude", ("claude",)),
)


@dataclass
class MetricsCollector:
    proc_root: Path | None = None
    sys_root: Path | None = None
    max_groups: int = 12
    tmpfs_fn: Callable[[str], tuple] | None = None
    # Teto de segurança: uma varredura truncada é nomeada `partial` e nunca se
    # disfarça de lista completa. 0 desliga o teto (usado só em diagnóstico).
    max_processes: int = 8192
    # Injetáveis para provar idade/histórico sem dormir em teste.
    clock: Callable[[], float] = time.monotonic
    wall_clock: Callable[[], float] = time.time
    ticks_per_sec: int = 0          # 0 = SC_CLK_TCK do host
    cpu_count: int = 0              # 0 = os.cpu_count()
    _prev_mono: float | None = field(default=None, init=False, repr=False)
    _prev_cpu: CpuTimes | None = field(default=None, init=False, repr=False)
    _prev_procs: dict[tuple[int, int], tuple[int, int]] = field(
        default_factory=dict, init=False, repr=False)
    _prev_io: dict[tuple[int, int], tuple[int | None, int | None]] = field(
        default_factory=dict, init=False, repr=False)

    def _proc(self) -> Path:
        return Path(self.proc_root) if self.proc_root else Path(paths.proc_root())

    def _sys(self) -> Path:
        return Path(self.sys_root) if self.sys_root else Path(paths.sys_root())

    def collect(self) -> Snapshot:
        started = self.clock()
        root = self._proc()
        errors = []
        sources: list[tuple[str, str, str]] = []

        def add(name: str, status: str, detail: str = "") -> None:
            sources.append((name, status, detail))

        def read_optional(name: str, path: Path, value, *, missing: str):
            if value is not None:
                add(name, OK)
            elif path.exists():
                add(name, ERROR, "arquivo presente, mas ilegível ou malformado")
            else:
                add(name, MISSING, missing)
            return value

        mem = procfs.read_meminfo(root)
        read_optional("meminfo", root / "meminfo", mem, missing="meminfo ausente")
        if mem is None:
            errors.append("meminfo unavailable")

        pressure_mem = read_optional(
            "pressure_memory", root / "pressure" / "memory",
            procfs.read_pressure(root, "memory"),
            missing="PSI de memória sem suporte ou desligado")
        pressure_io = read_optional(
            "pressure_io", root / "pressure" / "io",
            procfs.read_pressure(root, "io"),
            missing="PSI de I/O sem suporte ou desligado")
        pressure_cpu = read_optional(
            "pressure_cpu", root / "pressure" / "cpu",
            procfs.read_pressure(root, "cpu"),
            missing="PSI de CPU sem suporte ou desligado")
        load = read_optional("loadavg", root / "loadavg",
                             procfs.read_loadavg(root), missing="loadavg ausente")
        swaps = procfs.read_swaps(root)
        if (root / "swaps").exists():
            add("swaps", OK)
        else:
            add("swaps", MISSING, "swaps ausente")
        cpu = read_optional("cpu", root / "stat", procfs.read_cpu_times(root),
                            missing="stat de CPU ausente")

        scan = procfs.scan_processes(root, limit=self.max_processes)
        procs = list(scan.procs)
        if scan.error:
            add("processes", ERROR, scan.error)
            errors.append(f"processes unavailable: {scan.error}")
        elif scan.truncated or scan.unreadable:
            details = []
            if scan.truncated:
                details.append(
                    f"varredura limitada a {self.max_processes} de "
                    f"{scan.entries} entrada(s)")
            if scan.unreadable:
                details.append(
                    f"{len(scan.unreadable)} entrada(s) ilegível(is): "
                    + ", ".join(str(pid) for pid in scan.unreadable[:8]))
            add("processes", PARTIAL, "; ".join(details))
        else:
            add("processes", OK)

        volumes = self._collect_tmpfs(root, add)
        zram = read_optional(
            "zram", self._sys() / "block" / "zram0" / "mm_stat",
            sysfs.read_zram_mm_stat(self._sys()), missing="zram0 ausente")
        self_rss_kb, self_rss_error = self._self_rss(root)
        if self_rss_error:
            add("self_rss", ERROR, self_rss_error)
        else:
            add("self_rss", OK)

        finished = self.clock()
        elapsed = (None if self._prev_mono is None
                   else max(0.0, finished - self._prev_mono))
        cpu_busy_frac = self._cpu_fraction(cpu, elapsed)
        procs, io_seen = self._with_deltas(procs, elapsed, scan.error is not None)
        self._prev_cpu = cpu
        self._prev_mono = finished
        if procs:
            if io_seen == 0:
                add("process_io", MISSING,
                    "io por processo indisponível (permissão ou kernel)")
            elif io_seen < len(procs):
                add("process_io", PARTIAL,
                    f"io legível em {io_seen} de {len(procs)} processo(s)")
            else:
                add("process_io", OK)
        else:
            add("process_io", MISSING, "nenhum processo observado")

        try:
            boot_id = (root / "sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            boot_id = ""
        return Snapshot(
            boot_id=boot_id,
            ts=self.wall_clock(),
            mem=mem,
            swap_used_kb=sum(s.used_kb for s in swaps),
            swap_total_kb=sum(s.size_kb for s in swaps),
            pressure_memory=pressure_mem,
            pressure_io=pressure_io,
            pressure_cpu=pressure_cpu,
            load=load,
            apps=self._group_rss(procs),
            self_rss_kb=self_rss_kb,
            procs=tuple(procs),
            tmpfs=volumes,
            errors=tuple(errors),
            mono=finished,
            duration_s=max(0.0, finished - started),
            sources=tuple(SourceQuality(name, status, detail, finished)
                          for name, status, detail in sources),
            zram=zram,
            cpu=cpu,
            cpu_busy_frac=cpu_busy_frac,
            cpu_count=self.cpu_count or os.cpu_count() or 1,
        )

    def _cpu_fraction(self, cpu: CpuTimes | None, elapsed: float | None):
        if cpu is None or self._prev_cpu is None or elapsed is None or elapsed <= 0:
            return None
        total_delta = cpu.total - self._prev_cpu.total
        busy_delta = cpu.busy - self._prev_cpu.busy
        if total_delta <= 0:
            return None
        return max(0.0, min(1.0, busy_delta / total_delta))

    def _with_deltas(self, procs, elapsed, scan_failed):
        ticks = self.ticks_per_sec or _clock_ticks()
        updated = []
        io_seen = 0
        for proc in procs:
            key = (proc.pid, proc.starttime)
            cpu_frac = None
            previous = self._prev_procs.get(key)
            if previous is not None and elapsed is not None and elapsed > 0:
                delta = (proc.utime + proc.stime) - (previous[0] + previous[1])
                cpu_frac = max(0.0, 100.0 * delta / (ticks * elapsed))

            previous_io = self._prev_io.get(key)
            read_bps = write_bps = None
            if previous_io is not None and elapsed is not None and elapsed > 0:
                if proc.io_read_bytes is not None and previous_io[0] is not None:
                    read_bps = max(0.0, (proc.io_read_bytes - previous_io[0]) / elapsed)
                if proc.io_write_bytes is not None and previous_io[1] is not None:
                    write_bps = max(0.0, (proc.io_write_bytes - previous_io[1]) / elapsed)
            if proc.io_read_bytes is not None or proc.io_write_bytes is not None:
                io_seen += 1
            updated.append(replace(proc, cpu_frac=cpu_frac,
                                   io_read_bps=read_bps, io_write_bps=write_bps))

        if scan_failed:
            # Uma varredura que falhou não prova delta: o próximo poll recomeça.
            self._prev_procs.clear()
            self._prev_io.clear()
        else:
            self._prev_procs = {(p.pid, p.starttime): (p.utime, p.stime)
                                for p in updated}
            self._prev_io = {(p.pid, p.starttime):
                             (p.io_read_bytes, p.io_write_bytes)
                             for p in updated}
        return updated, io_seen

    def _collect_tmpfs(self, root: Path, add) -> tuple:
        if self.tmpfs_fn is not None:
            try:
                volumes = tuple(self.tmpfs_fn(str(root)))
            except Exception as exc:  # a seam quebrada não derruba o snapshot
                add("tmpfs", ERROR, f"{type(exc).__name__}: {exc}")
                return ()
            add("tmpfs", OK)
            return volumes
        mounts, error = tmpfs_read.read_mounts_checked(str(root))
        if error:
            status = MISSING if not (root / "mounts").exists() else ERROR
            add("tmpfs", status, error)
            return ()
        volumes = tmpfs_read.watched_volumes(proc_root=str(root), mounts=mounts)
        problems = [f"{v.path}: {v.error}" for v in volumes if v.quality != OK]
        add("tmpfs", PARTIAL if problems else OK, "; ".join(problems))
        return volumes

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
    def _self_rss(proc_root: Path) -> tuple[int, str | None]:
        # test seams may not carry 'self'; own process stats come from real /proc
        for candidate in (proc_root / "self", Path("/proc/self")):
            try:
                raw = (candidate / "status").read_text()
            except OSError:
                continue
            for line in raw.splitlines():
                if line.startswith("VmRSS:"):
                    try:
                        return int(line.split()[1]), None
                    except (IndexError, ValueError):
                        return 0, "VmRSS do próprio processo ilegível"
            return 0, "status do próprio processo sem VmRSS"
        return 0, "status do próprio processo indisponível"
