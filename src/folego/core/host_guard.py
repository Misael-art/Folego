"""Small, read-only host signals and guidance. No Qt or host effects."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .snapshot import OK, Snapshot

WINDOW_S = 240.0


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
                or not -20 <= value <= 150 or not snapshot.temperature_sensor):
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
        elif passive is not None and value >= passive:
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
        "em outro destino verificado. Evite novas escritas e varreduras desnecessárias. "
        "Planeje a desmontagem segura e uma verificação completa com chkdsk no Windows. "
        "ntfsfix não substitui essa verificação. Nenhum reparo é executado aqui."),
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
        "anteriores; investigue energia, temperatura, kernel e armazenamento com "
        "evidências próprias. O Fôlego não reinicia o host para testar."),
    "pressure": (
        "Pressão de CPU e I/O", "PSI mede a espera observada pelo kernel em uma janela "
        "de 60 segundos. Um valor alto pede correlação com tarefas e dispositivos; "
        "sozinho não prova qual aplicação causou o atraso. Revise o Modo Desempenho "
        "e os consumidores antes de reduzir uma tarefa pelo próprio aplicativo. "
        "O Fôlego não encerra processos por este indicador."),
}
