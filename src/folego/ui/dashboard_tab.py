"""M3 dashboard: the title-bar numbers, the reasons behind them, and a way out.

Plain data in (Snapshot plus the counts the window already computed), jump
requests out. This widget measures nothing and mutates nothing on purpose: the
rules live in ``core.suggestions``, so the same verdicts are testable without a
display and reusable by the tray tooltip.
"""
from PySide6.QtCore import Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from . import title_signal
from ..core.snapshot import ERROR, MISSING, PARTIAL
from ..core.suggestions import suggest

LEVEL_EMOJI = {"critico": "🔴", "alto": "🟠", "medio": "🟡"}
TARGET_LABEL = {"memoria": "memória", "ajustes": "ajustes",
                "orfaos": "órfãos", "disco": "disco"}


class SuggestionRow(QWidget):
    def __init__(self, suggestion, on_jump, parent=None):
        super().__init__(parent)
        self.suggestion = suggestion
        self.target = suggestion.target
        self._on_jump = on_jump
        self.text_label = QLabel()
        self.text_label.setWordWrap(True)
        self.why_label = QLabel()
        self.why_label.setWordWrap(True)
        self.why_label.setObjectName("why")
        self.jump_button = QPushButton()
        self.jump_button.clicked.connect(self._jump_requested)
        self.update_suggestion(suggestion)

        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(self.text_label)
        left.addWidget(self.why_label)
        layout = QHBoxLayout(self)
        layout.addLayout(left, 1)
        layout.addWidget(self.jump_button, 0)

    @Slot()
    def _jump_requested(self):
        self._on_jump(self.target)

    def update_suggestion(self, suggestion):
        """Atualiza no lugar: um poll igual não recria botões nem perde foco."""
        self.suggestion = suggestion
        self.target = suggestion.target
        self.text_label.setText(
            f"{LEVEL_EMOJI.get(suggestion.level, '·')} {suggestion.text}")
        self.why_label.setText(suggestion.why)
        self.jump_button.setText(
            f"Ir para {TARGET_LABEL.get(suggestion.target, 'aba')}")


class DashboardTab(QWidget):
    def __init__(self, *, on_jump=None, thresholds: title_signal.Thresholds | None = None,
                 parent=None):
        super().__init__(parent)
        self._jump = on_jump or (lambda target: None)
        # the same thresholds the title uses: two signals, one verdict
        self._thresholds = thresholds or title_signal.Thresholds()
        self.rows: list[SuggestionRow] = []

        self.headline = QLabel("Aguardando primeira leitura…")
        self.headline.setObjectName("headline")
        self.headline.setWordWrap(True)
        self.details = QLabel("")
        self.details.setWordWrap(True)
        self.resources = QLabel("saúde por recurso: aguardando a primeira amostra.")
        self.resources.setObjectName("quality")
        self.resources.setWordWrap(True)
        self.resources.setAccessibleName("Saúde e qualidade da coleta")
        self.last_operation = QLabel("última operação: ainda não consultada.")
        self.last_operation.setObjectName("quality")
        self.last_operation.setWordWrap(True)
        self.last_operation.setAccessibleName("Última operação registrada")
        self.automation_status = QLabel(
            "automação: estado ainda não lido; execução real desligada.")
        self.automation_status.setObjectName("quality")
        self.automation_status.setWordWrap(True)
        self.automation_status.setAccessibleName(
            "Modo da automação, preset e grants; somente leitura nesta versão")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.copy_button = QPushButton("Copiar diagnóstico")
        self.copy_button.setAccessibleName(
            "Copiar um diagnóstico legível, sem comandos nem credenciais")
        self.copy_button.clicked.connect(self.copy_diagnostic)

        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(6)
        self._hidden_rows: list[SuggestionRow] = []
        holder = QWidget()
        holder.setLayout(self.list_box)
        scroll_rows = QVBoxLayout()
        scroll_rows.addWidget(holder)
        scroll_rows.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.headline)
        layout.addWidget(self.details)
        layout.addWidget(self.resources)
        layout.addWidget(self.last_operation)
        layout.addWidget(self.automation_status)
        layout.addLayout(scroll_rows)
        layout.addWidget(self.status)
        layout.addWidget(self.copy_button, 0)

    def show_snapshot(self, snapshot, *, orphan_count: int = 0,
                      thumbnails_kb: int | None = None,
                      extra_notes=(), signal=None, last_operation: str = ""):
        signal = signal or title_signal.compute(snapshot, self._thresholds)
        self.headline.setText(signal.text)
        self.details.setText(self._details(snapshot))
        self.resources.setText(self._resources(snapshot))
        if last_operation:
            self.last_operation.setText(f"última operação: {last_operation}")
        self._sync_rows(suggest(snapshot, orphan_count=orphan_count,
                                thumbnails_kb=thumbnails_kb))

        notes = [f"não foi possível ler: {e}" for e in snapshot.errors]
        for quality in snapshot.sources:
            if quality.status in (ERROR, PARTIAL):
                notes.append(f"{quality.name} {quality.status}: {quality.detail}")
            elif quality.status == MISSING and quality.name in ("meminfo", "processes"):
                notes.append(f"{quality.name} missing: {quality.detail}")
        if signal.report is not None:
            for reason in signal.report.reasons:
                if reason.code in ("snapshot_stale", "hysteresis") or \
                        reason.severity == "critico":
                    notes.append(reason.message)
        if not self.rows and not notes:
            notes.append("nada a sugerir: memória, pressão, zram e Edge estão "
                         "dentro do orçamento")
        notes.extend(extra_notes)
        self.status.setText(" · ".join(notes))

    def show_automation(self, *, mode: str, preset: str, paused: bool,
                        active_grants: int, error: str = "") -> None:
        """Read-only F6 state: a preset never looks like a grant.

        Execution is intentionally not offered here while the simulation gate is
        not validated; the line says that in words so a green mode is not mistaken
        for an active automation.
        """
        if error:
            self.automation_status.setText(
                f"automação: estado ilegível — fail-closed; execução desligada "
                f"({error})")
            return
        state = "pausada" if paused else "não pausada"
        grants = (f"{active_grants} grant(s) ativo(s)"
                 if active_grants else "nenhum grant ativo")
        self.automation_status.setText(
            f"automação: modo {mode} · preset {preset} · {state} · {grants} · "
            "somente leitura; execução real desligada nesta versão")

    def _resources(self, snapshot) -> str:
        """One line per resource, in words; colour is never the only signal."""
        parts = []
        if snapshot.mem is None:
            parts.append("memória: sem dados")
        else:
            avail_frac = (snapshot.mem.mem_available_kb /
                          max(1, snapshot.mem.mem_total_kb))
            if avail_frac < self._thresholds.red_available_frac:
                level = "crítico"
            elif avail_frac < self._thresholds.yellow_available_frac:
                level = "atenção"
            else:
                level = "ok"
            parts.append(f"memória: {level} ({avail_frac * 100:.0f}% livre)")
        if snapshot.swap_total_kb:
            used = snapshot.swap_used_kb / max(1, snapshot.swap_total_kb)
            parts.append(f"swap/zram: {used * 100:.0f}% usado")
        if snapshot.tmpfs:
            for volume in snapshot.tmpfs:
                if volume.quality != "ok":
                    parts.append(f"{volume.path}: capacidade desconhecida ({volume.error})")
                if volume.is_runtime and (volume.used_frac >= .9 or
                        (volume.inodes_total > 0 and volume.inodes_avail == 0)):
                    parts.append("Runtime da sessão crítico — aplicativos podem não abrir")
            worst = max(snapshot.tmpfs, key=lambda volume: volume.used_frac)
            parts.append(f"tmpfs {worst.path}: {worst.used_frac * 100:.0f}% usado")
        else:
            parts.append("tmpfs: sem volume observado")
        if snapshot.cpu_busy_frac is None:
            parts.append("cpu: delta ainda não disponível")
        else:
            parts.append(f"cpu: {snapshot.cpu_busy_frac * 100:.0f}% em uso")
        if snapshot.procs:
            parts.append(f"processos: {len(snapshot.procs)} observados")
        qualities = snapshot.sources
        if qualities:
            counts = {}
            for quality in qualities:
                counts[quality.status] = counts.get(quality.status, 0) + 1
            summary = ", ".join(f"{name} {counts[name]}"
                                for name in ("ok", "partial", "missing", "error")
                                if name in counts)
            parts.append(f"coleta: {summary}")
        else:
            parts.append("coleta: fontes não declaradas")
        blockers = snapshot.action_blockers(required=())
        if blockers:
            parts.append("ação bloqueada: " + "; ".join(blockers))
        return "saúde por recurso · " + " · ".join(parts)

    def diagnostic_text(self) -> str:
        """Sanitized copy: verdicts and counts, never commands or credentials."""
        return "\n".join(text for text in (
            self.headline.text(), self.details.text(), self.resources.text(),
            self.last_operation.text(), self.automation_status.text(),
            self.status.text()) if text)

    def copy_diagnostic(self):
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.diagnostic_text())

    def _details(self, snapshot) -> str:
        if snapshot.mem is None:
            return "coleta sem meminfo"
        total = snapshot.mem.mem_total_kb
        avail = snapshot.mem.mem_available_kb
        parts = [f"usada {title_signal.fmt1((total - avail) / title_signal.MB)} GB / "
                 f"{title_signal.fmt1(total / title_signal.MB)} GB",
                 f"livre {title_signal.fmt1(avail / title_signal.MB)} GB",
                 f"app {snapshot.self_rss_kb // title_signal.KB} MB"]
        if snapshot.cpu_busy_frac is not None:
            parts.append(f"cpu {snapshot.cpu_busy_frac * 100:.0f}% de "
                         f"{snapshot.cpu_count} cpu(s)")
        if snapshot.zram is not None:
            parts.append("zram usado "
                         f"{title_signal.fmt1(snapshot.zram.mem_used_total_kb / title_signal.KB)} MB"
                         f" · comprimido "
                         f"{title_signal.fmt1(snapshot.zram.compr_data_kb / title_signal.KB)} MB")
        if snapshot.swap_total_kb:
            pct = snapshot.swap_used_kb * 100 // snapshot.swap_total_kb
            parts.append(f"zram/swap {title_signal.fmt1(snapshot.swap_used_kb / title_signal.MB)} GB "
                         f"({pct}%)")
        if snapshot.pressure_memory:
            parts.append(f"psi/memória avg10 "
                         f"{snapshot.pressure_memory.some_avg10:.1f}".replace(".", ","))
            if snapshot.pressure_memory.full_avg10 is not None:
                parts.append(f"psi/full "
                             f"{snapshot.pressure_memory.full_avg10:.1f}".replace(".", ","))
        if snapshot.load:
            parts.append(f"load 1m {snapshot.load.one:.2f}".replace(".", ","))
        if snapshot.apps:
            parts.append("top apps (RSS estimado) " + ", ".join(
                f"{a.group} {a.rss_kb // title_signal.KB} MB" for a in snapshot.apps[:5]))
        if snapshot.ts_iso:
            parts.append(f"amostra {snapshot.ts_iso}")
        return " · ".join(parts)

    def _sync_rows(self, suggestions):
        by_id = {row.suggestion.id: row for row in self.rows}
        rows = []
        for suggestion in suggestions:
            row = by_id.pop(suggestion.id, None)
            if row is None and self._hidden_rows:
                # Reaproveita uma linha oculta em vez de destruí-la: `deleteLater`
                # de um QWidget com sinal conectado a um lambda já derrubou o
                # ensaio F8 (double free no Shiboken). O pool nunca passa do
                # número de sugestões simultâneas.
                row = self._hidden_rows.pop()
                row.update_suggestion(suggestion)
            elif row is None:
                row = SuggestionRow(suggestion, self._jump)
            else:
                row.update_suggestion(suggestion)
            rows.append(row)
        for stale in by_id.values():
            # O layout devolve o espaço na hora; o widget fica oculto e vive
            # para o próximo poll, sem destruir C++/Python em pleno loop.
            self.list_box.removeWidget(stale)
            stale.hide()
            self._hidden_rows.append(stale)
        for index, row in enumerate(rows):
            item = self.list_box.itemAt(index)
            if item is None or item.widget() is not row:
                self.list_box.insertWidget(index, row)
            row.show()
        self.rows = rows
