"""Pure data containers for one metrics sample. No logic, no Qt."""
import time
from dataclasses import dataclass, field
from datetime import datetime

from .tmpfs import TmpfsVolume

# Estados de uma fonte de coleta. `partial` é utilizável com ressalva; os outros
# dois (missing/error) nunca podem autorizar uma ação.
OK = "ok"
PARTIAL = "partial"
MISSING = "missing"
ERROR = "error"


@dataclass(frozen=True)
class SourceQuality:
    """O que foi lido, quando, e o quanto isso merece confiança."""

    name: str
    status: str = MISSING
    detail: str = ""
    mono: float = 0.0

    @property
    def usable(self) -> bool:
        return self.status in (OK, PARTIAL)

    def age_s(self, now_mono: float | None = None) -> float:
        if self.mono <= 0:
            return 0.0
        now = time.monotonic() if now_mono is None else now_mono
        return max(0.0, now - self.mono)


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
    # `full` só existe para alguns recursos/kernels; None é "não fornecido",
    # nunca zero. Quem decide severidade não pode tratar ausência como alívio.
    full_avg10: float | None = None
    full_avg60: float | None = None
    full_avg300: float | None = None
    full_total: int | None = None


@dataclass(frozen=True)
class ZramStat:
    orig_data_kb: int
    compr_data_kb: int
    mem_used_total_kb: int


@dataclass(frozen=True)
class CpuTimes:
    """Contadores acumulados de /proc/stat; a fração só nasce de deltas."""

    user: int
    nice: int
    system: int
    idle: int
    iowait: int
    irq: int
    softirq: int
    steal: int

    @property
    def total(self) -> int:
        return (self.user + self.nice + self.system + self.idle + self.iowait
                + self.irq + self.softirq + self.steal)

    @property
    def busy(self) -> int:
        return self.total - self.idle - self.iowait


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
    # Opcionais: None significa "não observado", nunca zero. `cpu_frac` é a
    # fração de UM CPU no intervalo entre duas coletas; I/O é acumulado em bytes
    # e os bps também só existem depois de um delta.
    cpu_frac: float | None = None
    io_read_bytes: int | None = None
    io_write_bytes: int | None = None
    io_read_bps: float | None = None
    io_write_bps: float | None = None
    pss_kb: int | None = None

    @property
    def rss_is_estimate(self) -> bool:
        """VmRSS é estimativa: não desconta páginas compartilhadas (PSS)."""
        return True


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
    tmpfs: tuple[TmpfsVolume, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)
    # `ts` continua sendo o relógio de parede (compatibilidade e exibição);
    # `mono` é o relógio monotônico do fim da coleta — idade e frescor usam este,
    # porque parede pode saltar com NTP/fuso e não prova intervalo.
    mono: float = 0.0
    duration_s: float = 0.0
    sources: tuple[SourceQuality, ...] = ()
    zram: ZramStat | None = None
    cpu: CpuTimes | None = None
    cpu_busy_frac: float | None = None
    cpu_count: int = 0
    boot_id: str = ""

    @property
    def ts_iso(self) -> str:
        """Timestamp humano local; vazio quando a amostra não tem relógio de parede."""
        if not self.ts:
            return ""
        return datetime.fromtimestamp(self.ts).astimezone().isoformat(timespec="seconds")

    def source(self, name: str) -> SourceQuality:
        for item in self.sources:
            if item.name == name:
                return item
        return SourceQuality(name, MISSING, "fonte não coletada")

    def usable(self, name: str) -> bool:
        return self.source(name).usable

    def age_s(self, now_mono: float | None = None) -> float:
        if self.mono <= 0:
            return 0.0
        now = time.monotonic() if now_mono is None else now_mono
        return max(0.0, now - self.mono)

    def is_stale(self, max_age_s: float, now_mono: float | None = None) -> bool:
        # Sem relógio monotônico não há como provar que a amostra é fresca.
        if self.mono <= 0:
            return True
        return self.age_s(now_mono) > max_age_s

    def action_blockers(self, *, required: tuple[str, ...] = ("meminfo",),
                        max_age_s: float = 15.0,
                        now_mono: float | None = None) -> tuple[str, ...]:
        """Motivos pelos quais esta amostra não pode autorizar uma ação.

        Ausente, ilegível ou antigo nunca vira "vazio/seguro": o chamador que
        exige fresco recebe uma lista não vazia e recusa. `partial` continua
        utilizável, mas o motivo fica registrado na qualidade da fonte.
        """
        reasons = []
        if self.mono <= 0:
            reasons.append("snapshot sem relógio monotônico: idade não comprovada")
        elif self.age_s(now_mono) > max_age_s:
            reasons.append(
                f"snapshot com {self.age_s(now_mono):.1f}s "
                f"(limite {max_age_s:g}s)")
        for name in required:
            quality = self.source(name)
            if not quality.usable:
                reasons.append(
                    f"{name} {quality.status}: {quality.detail or 'sem detalhe'}")
        return tuple(reasons)
