"""Small, read-only host signals and guidance. No Qt or host effects."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
import time

from .snapshot import OK, Snapshot

WINDOW_S = 240.0
_PRESSURE_LIMITS = (("memory", "pressure_memory", 5.0),
                    ("io", "pressure_io", 10.0),
                    ("cpu", "pressure_cpu", 25.0))


@dataclass
class PressureAlertTracker:
    """Warn on sustained kernel PSI already present in resource snapshots."""

    boot_id: str = ""
    pending: dict[str, tuple[float, float]] = field(default_factory=dict)
    last_notice: dict[str, float] = field(default_factory=dict)
    visible: dict[str, tuple[str, float | None]] = field(default_factory=dict)

    def visible_status(self) -> list[dict]:
        """Current sustained risk, or an unknown reading after that risk."""
        return [{"kind": name, "state": state, "value": value}
                for name, (state, value) in self.visible.items()]

    def observe(self, snapshot: Snapshot, *, now_mono: float | None = None) -> dict | None:
        now = time.monotonic() if now_mono is None else now_mono
        if snapshot.boot_id != self.boot_id:
            self.boot_id = snapshot.boot_id
            self.pending.clear()
            self.last_notice.clear()
            self.visible.clear()
        if snapshot.is_stale(15, now):
            self.pending.clear()
            self.visible = {name: ("unknown", None) for name in self.visible}
            return None
        alerts = []
        for name, source, limit in _PRESSURE_LIMITS:
            pressure = getattr(snapshot, source)
            value = pressure.some_avg60 if pressure is not None else None
            if (snapshot.source(source).status != OK or value is None
                    or not math.isfinite(value) or not 0 <= value <= 100):
                self.pending.pop(name, None)
                if name in self.visible:
                    self.visible[name] = ("unknown", None)
                continue  # missing data cannot prove recovery or sustained pressure
            if value < limit:
                self.pending.pop(name, None)
                self.visible.pop(name, None)
                continue
            first, previous = self.pending.get(name, (snapshot.mono, snapshot.mono))
            if snapshot.mono < previous or snapshot.mono - previous > 20:
                first = snapshot.mono  # a gap does not prove continuous pressure
            self.pending[name] = (first, snapshot.mono)
            if snapshot.mono - first < 15:
                continue
            self.visible[name] = ("high", round(value, 1))
            previous_notice = self.last_notice.get(name)
            if previous_notice is None or now - previous_notice >= 300:
                alerts.append({"kind": name, "source": source,
                               "value": round(value, 1), "window_s": 60,
                               "sample_at": snapshot.ts_iso,
                               "age_s": round(snapshot.age_s(now), 1)})
                self.last_notice[name] = now
        # One notification carries every newly due signal; none is hidden by
        # the shared rate limit or emitted as a burst of separate popups.
        if not alerts:
            return None
        alerts[0]["also"] = [{"kind": item["kind"], "value": item["value"]}
                             for item in alerts[1:]]
        return alerts[0]


@dataclass
class ThermalTracker:
    """Keep four minutes of fresh samples; never call ACPI a CPU thermometer."""

    samples: deque = field(default_factory=lambda: deque(maxlen=150))
    identity: tuple[str, str] | None = None

    def observe(self, snapshot: Snapshot) -> dict:
        now = snapshot.mono
        identity = (snapshot.boot_id, snapshot.temperature_sensor)
        if self.identity != identity:
            self.samples.clear()
            self.identity = identity
        while self.samples and now - self.samples[0][0] > WINDOW_S:
            self.samples.popleft()
        value = snapshot.temperature_c
        if (now <= 0 or snapshot.is_stale(15) or value is None
                or not -20 <= value <= 150 or not snapshot.temperature_sensor
                or (snapshot.sources and snapshot.source("temperature").status != OK)):
            return {"state": "unknown", "reason": "temperatura ausente ou antiga",
                    "current_c": None, "peak_c": None, "sensor": snapshot.temperature_sensor,
                    "fan_rpm": snapshot.fan_rpm, "passive_c": None,
                    "critical_c": None, "top_process": None,
                    "pressure_io_avg60": (snapshot.pressure_io.some_avg60
                                          if snapshot.pressure_io else None),
                    "pressure_cpu_avg60": (snapshot.pressure_cpu.some_avg60
                                           if snapshot.pressure_cpu else None)}
        top = None
        if snapshot.source("processes").status == OK:
            observed = [p for p in snapshot.procs if p.cpu_frac is not None]
            if observed:
                proc = max(observed, key=lambda p: p.cpu_frac)
                if proc.cpu_frac >= 20:
                    top = {"name": proc.comm[:80], "pid": proc.pid,
                           "starttime": proc.starttime, "cpu_percent_of_core": round(proc.cpu_frac, 1)}
        self.samples.append((now, value, top))
        peak = max(self.samples, key=lambda item: item[1])
        passive = snapshot.thermal_passive_c
        critical = snapshot.thermal_critical_c
        limit = passive if passive is not None else critical
        state = "observed"
        if critical is not None and value >= critical:
            state = "critical"
        elif limit is not None and value >= limit:
            state = "danger"
        elif limit is not None and value >= limit - 5:
            state = "high"
        elif limit is not None and peak[1] >= limit - 5:
            state = "recent_high"
        return {"state": state, "current_c": round(value, 1),
                "peak_c": round(peak[1], 1), "sensor": snapshot.temperature_sensor,
                "fan_rpm": snapshot.fan_rpm, "passive_c": passive,
                "critical_c": critical, "top_process": peak[2],
                "pressure_io_avg60": (snapshot.pressure_io.some_avg60
                                      if snapshot.pressure_io else None),
                "pressure_cpu_avg60": (snapshot.pressure_cpu.some_avg60
                                       if snapshot.pressure_cpu else None)}


GUIDES = {
    "thermal": (
        "Calor e carga", "Confira a leitura e sua origem (ACPI pode medir uma zona do sistema, não a CPU). "
        "Observe as tarefas com CPU alta; se a temperatura continuar próxima do limite, "
        "salve o trabalho e reduza a tarefa pelo aplicativo responsável. Sem tacômetro, "
        "a rotação da ventoinha continua desconhecida. O Fôlego não altera a ventoinha "
        "nem encerra agentes por este aviso."),
    "ntfs": (
        "Avisos NTFS", "Identifique o volume e preserve primeiro os dados insubstituíveis "
        "em outro destino persistente e verificado. Evite novas escritas e varreduras "
        "desnecessárias. Pelo Linux, planeje uma imagem recuperável do volume desmontado, "
        "investigue uma cópia e extraia os arquivos com verificação. ntfsfix só corrige "
        "alguns problemas fundamentais; não garante reparar índices NTFS. Recrie o volume "
        "e restaure apenas depois de preservar uma cópia certificada. Sem destino suficiente, "
        "não tente reparar o cartão original."),
    "btrfs": (
        "Contadores Btrfs", "O número acumulado não mostra sozinho quando ocorreu o erro. "
        "Priorize backup verificado se a contagem crescer. Um scrub planejado pode verificar "
        "os dados, mas consome I/O e só corrige blocos quando existe cópia íntegra. "
        "Não execute btrfs check --repair automaticamente ou no filesystem montado."),
    "service": (
        "Serviço em falha", "Confira a unit exata e o projeto que a instalou. "
        "Corrija o alvo e limite os reinícios no responsável pelo serviço. "
        "O Fôlego não para, desabilita ou substitui units alheias automaticamente."),
    "reboot": (
        "Reinícios anteriores", "O fim de um diário sem registro de desligamento "
        "não prova a causa do reinício. Preserve horários, boot IDs e mensagens "
        "anteriores; compare com as amostras locais de RAM, swap, pressão e calor, "
        "quando disponíveis. Investigue energia, kernel e armazenamento com "
        "evidências próprias. O Fôlego não reinicia o host para testar."),
    "pressure": (
        "Pressão de CPU e I/O", "PSI mede a espera observada pelo kernel em uma janela "
        "de 60 segundos. Um valor alto pede correlação com tarefas e dispositivos; "
        "sozinho não prova qual aplicação causou o atraso. Revise o Modo Desempenho "
        "e os consumidores antes de reduzir uma tarefa pelo próprio aplicativo. "
        "O Fôlego não encerra processos por este indicador."),
}
