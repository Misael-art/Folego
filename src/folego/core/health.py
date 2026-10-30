"""Health verdicts over one Snapshot. Pure Python: no Qt, no /proc, no writes.

The engine is deliberately stateful across polls: escalation is immediate (a
problem should never wait for a second sample to be shown), while de-escalation
needs `recovery_samples` consecutive observations. A single good sample does not
erase a red verdict, and a stale/absent source never becomes green by default.

Thresholds carry a version so a verdict can be audited against the rules that
produced it. Reasons are structured (code/metric/value/threshold), not prose
only, because both the UI and the CLI must be able to explain a refusal.
"""
from dataclasses import dataclass, field

from .snapshot import ERROR, MISSING, PARTIAL, Snapshot
THRESHOLDS_VERSION = 1
GREEN = "green"
YELLOW = "yellow"
RED = "red"
UNKNOWN = "unknown"

_RANK = {GREEN: 0, YELLOW: 1, RED: 2}
_SEVERITY = {RED: "critico", YELLOW: "alto", GREEN: "medio", UNKNOWN: "critico"}


@dataclass(frozen=True)
class HealthThresholds:
    version: int = THRESHOLDS_VERSION
    yellow_available_frac: float = 0.20
    red_available_frac: float = 0.10
    psi_memory_yellow: float = 5.0
    psi_memory_red: float = 10.0
    psi_full_yellow: float = 5.0
    psi_full_red: float = 10.0
    self_rss_yellow_kb: int = 300_000
    tmpfs_yellow_frac: float = 0.75
    tmpfs_red_frac: float = 0.90
    stale_after_s: float = 15.0
    recovery_samples: int = 3


@dataclass(frozen=True)
class Reason:
    code: str
    severity: str
    message: str
    metric: str = ""
    value: float | int | None = None
    threshold: float | int | None = None
    source: str = ""


@dataclass(frozen=True)
class HealthReport:
    level: str
    raw_level: str
    reasons: tuple[Reason, ...]
    thresholds_version: int
    stale: bool = False
    age_s: float | None = None
    mono: float | None = None

    @property
    def unknown(self) -> bool:
        return self.level == UNKNOWN

    @property
    def degraded(self) -> bool:
        return any(reason.severity in ("info", "medio") for reason in self.reasons)

    def codes(self) -> tuple[str, ...]:
        return tuple(reason.code for reason in self.reasons)


@dataclass
class HealthEngine:
    thresholds: HealthThresholds = field(default_factory=HealthThresholds)
    _level: str | None = field(default=None, init=False, repr=False)
    _candidate: str | None = field(default=None, init=False, repr=False)
    _streak: int = field(default=0, init=False, repr=False)

    def evaluate(self, snapshot: Snapshot, now_mono: float | None = None
                 ) -> HealthReport:
        raw, reasons, stale, age = self._judge(snapshot, now_mono)
        level = self._stabilize(raw)
        if level != raw and level != UNKNOWN:
            reasons.append(Reason(
                "hysteresis", "info",
                f"sinal mantido em {level} até {self.thresholds.recovery_samples} "
                "amostras consecutivas melhores",
                metric="level", value=level, threshold=raw))
        return HealthReport(
            level=level, raw_level=raw, reasons=tuple(reasons),
            thresholds_version=self.thresholds.version,
            stale=stale, age_s=age, mono=snapshot.mono or None)

    def _judge(self, snapshot: Snapshot, now_mono: float | None
               ) -> tuple[str, list[Reason], bool, float | None]:
        reasons: list[Reason] = []
        stale = False
        age = None
        # Uma amostra real (com fontes declaradas) sem relógio monotônico não
        # prova idade. Snapshots sintéticos antigos (sem fontes) seguem válidos
        # para os testes puros de título.
        if snapshot.mono > 0:
            age = snapshot.age_s(now_mono)
            if age > self.thresholds.stale_after_s:
                stale = True
        elif snapshot.sources:
            stale = True
        if stale:
            detail = ("sem relógio monotônico: idade não comprovada"
                      if snapshot.mono <= 0
                      else f"{age:.1f}s desde a coleta "
                           f"(limite {self.thresholds.stale_after_s:g}s)")
            reasons.append(Reason(
                "snapshot_stale", "critico", f"amostra antiga: {detail}",
                metric="age_s", value=age,
                threshold=self.thresholds.stale_after_s, source="snapshot"))
            return UNKNOWN, reasons, True, age

        for quality in snapshot.sources:
            if quality.status in (ERROR, PARTIAL):
                reasons.append(Reason(
                    "source_" + quality.status, "medio",
                    f"{quality.name} {quality.status}: {quality.detail}",
                    source=quality.name))
        processes = snapshot.source("processes")
        if snapshot.sources and processes.status == MISSING:
            reasons.append(Reason(
                "processes_missing", "critico",
                "processos não observados: nenhum órfão pode ser afirmado",
                source="processes"))

        if snapshot.mem is None:
            reasons.append(Reason("meminfo_missing", "critico",
                                  "meminfo indisponível", source="meminfo"))
            return UNKNOWN, reasons, False, age

        total = snapshot.mem.mem_total_kb
        avail = snapshot.mem.mem_available_kb
        frac = avail / total if total else 0.0
        if frac < self.thresholds.red_available_frac:
            reasons.append(Reason(
                "memoria_red", _SEVERITY[RED],
                f"RAM disponível em {frac * 100:.0f}% (limite "
                f"{self.thresholds.red_available_frac * 100:g}%)",
                metric="available_frac", value=frac,
                threshold=self.thresholds.red_available_frac, source="meminfo"))
        elif frac < self.thresholds.yellow_available_frac:
            reasons.append(Reason(
                "memoria_yellow", _SEVERITY[YELLOW],
                f"RAM disponível em {frac * 100:.0f}% (limite "
                f"{self.thresholds.yellow_available_frac * 100:g}%)",
                metric="available_frac", value=frac,
                threshold=self.thresholds.yellow_available_frac, source="meminfo"))

        pressure = snapshot.pressure_memory
        if pressure is None:
            reasons.append(Reason(
                "pressure_missing", "info",
                "PSI de memória ausente: a decisão usa só RAM disponível",
                source="pressure_memory"))
        else:
            if pressure.some_avg10 > self.thresholds.psi_memory_red:
                reasons.append(Reason(
                    "psi_some_red", _SEVERITY[RED],
                    f"PSI some {pressure.some_avg10:.1f} > "
                    f"{self.thresholds.psi_memory_red:g}",
                    metric="psi_some_avg10", value=pressure.some_avg10,
                    threshold=self.thresholds.psi_memory_red,
                    source="pressure_memory"))
            elif pressure.some_avg10 > self.thresholds.psi_memory_yellow:
                reasons.append(Reason(
                    "psi_some_yellow", _SEVERITY[YELLOW],
                    f"PSI some {pressure.some_avg10:.1f} > "
                    f"{self.thresholds.psi_memory_yellow:g}",
                    metric="psi_some_avg10", value=pressure.some_avg10,
                    threshold=self.thresholds.psi_memory_yellow,
                    source="pressure_memory"))
            if pressure.full_avg10 is not None:
                if pressure.full_avg10 > self.thresholds.psi_full_red:
                    reasons.append(Reason(
                        "psi_full_red", _SEVERITY[RED],
                        f"PSI full {pressure.full_avg10:.1f} > "
                        f"{self.thresholds.psi_full_red:g}: tarefas paradas",
                        metric="psi_full_avg10", value=pressure.full_avg10,
                        threshold=self.thresholds.psi_full_red,
                        source="pressure_memory"))
                elif pressure.full_avg10 > self.thresholds.psi_full_yellow:
                    reasons.append(Reason(
                        "psi_full_yellow", _SEVERITY[YELLOW],
                        f"PSI full {pressure.full_avg10:.1f} > "
                        f"{self.thresholds.psi_full_yellow:g}",
                        metric="psi_full_avg10", value=pressure.full_avg10,
                        threshold=self.thresholds.psi_full_yellow,
                        source="pressure_memory"))

        if snapshot.self_rss_kb > self.thresholds.self_rss_yellow_kb:
            reasons.append(Reason(
                "self_rss", _SEVERITY[YELLOW],
                f"o próprio Fôlego usa {snapshot.self_rss_kb} kB",
                metric="self_rss_kb", value=snapshot.self_rss_kb,
                threshold=self.thresholds.self_rss_yellow_kb,
                source="self_rss"))

        for volume in snapshot.tmpfs:
            if volume.quality != "ok":
                reasons.append(Reason("tmpfs_unknown", "alto",
                                      f"{volume.path}: capacidade desconhecida ({volume.error})",
                                      source="tmpfs"))
                continue
            if volume.inodes_total > 0 and volume.inodes_avail == 0:
                reasons.append(Reason("tmpfs_inodes_exhausted", "critico",
                                      f"{volume.path}: inodes esgotados — aplicativos podem não abrir",
                                      source="tmpfs"))
            if volume.total_bytes > 0 and volume.avail_bytes == 0:
                reasons.append(Reason("tmpfs_bytes_exhausted", "critico",
                                      f"{volume.path}: sem bytes disponíveis — aplicativos podem não abrir",
                                      source="tmpfs"))
            if volume.is_runtime and volume.used_frac >= self.thresholds.tmpfs_red_frac:
                reasons.append(Reason("runtime_critical", "critico",
                                      "Runtime da sessão crítico — aplicativos podem não abrir",
                                      source="tmpfs"))
            if volume.total_bytes <= 0:
                continue
            if volume.used_frac >= self.thresholds.tmpfs_red_frac:
                reasons.append(Reason(
                    "tmpfs_red", _SEVERITY[RED],
                    f"{volume.path} em {volume.used_frac * 100:.0f}%",
                    metric="tmpfs_used_frac", value=volume.used_frac,
                    threshold=self.thresholds.tmpfs_red_frac,
                    source="tmpfs"))
            elif volume.used_frac >= self.thresholds.tmpfs_yellow_frac:
                reasons.append(Reason(
                    "tmpfs_yellow", _SEVERITY[YELLOW],
                    f"{volume.path} em {volume.used_frac * 100:.0f}%",
                    metric="tmpfs_used_frac", value=volume.used_frac,
                    threshold=self.thresholds.tmpfs_yellow_frac,
                    source="tmpfs"))

        if snapshot.zram is None and snapshot.sources:
            reasons.append(Reason(
                "zram_missing", "info", "zram0 não observado",
                source="zram"))
        level = GREEN
        for reason in reasons:
            if reason.severity == _SEVERITY[RED]:
                level = RED
                break
            if reason.severity == _SEVERITY[YELLOW]:
                level = YELLOW
        return level, reasons, False, age

    def _stabilize(self, raw: str) -> str:
        if raw == UNKNOWN:
            self._level = UNKNOWN
            self._candidate = None
            self._streak = 0
            return UNKNOWN
        if self._level is None or self._level == UNKNOWN:
            self._level = raw
            self._candidate = None
            self._streak = 0
            return raw
        if _RANK[raw] >= _RANK[self._level]:
            self._level = raw
            self._candidate = None
            self._streak = 0
            return raw
        # Só desce um degrau por vez; cada degrau exige amostras consecutivas.
        target = YELLOW if self._level == RED else GREEN
        if _RANK[raw] > _RANK[target]:
            target = raw
        if self._candidate == target:
            self._streak += 1
        else:
            self._candidate = target
            self._streak = 1
        if self._streak >= max(1, self.thresholds.recovery_samples):
            self._level = target
            self._candidate = None
            self._streak = 0
        return self._level
