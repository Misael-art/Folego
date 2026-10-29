"""M3 dashboard: the title-bar numbers, the reasons behind them, and a way out.

Layout follows the usual maintenance-dashboard pattern: a health gauge with the
verdict and one primary action at the top, one card per resource, the
recommendations, then recent activity. The gauge shows the smallest headroom
among the measured resources; the verdict word and colour come from the same
health report as the title, so the two never disagree.

Plain data in (Snapshot plus the counts the window already computed), jump
requests out. This widget measures nothing and mutates nothing on purpose: the
rules live in ``core.suggestions``, so the same verdicts are testable without a
display and reusable by the tray tooltip.
"""
from PySide6.QtCore import QRectF, Qt, Slot
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from . import title_signal
from .theme import TOKENS
from ..core import health
from ..core.snapshot import ERROR, MISSING, PARTIAL
from ..core.suggestions import suggest

LEVEL_EMOJI = {"critico": "🔴", "alto": "🟠", "medio": "🟡"}
TARGET_LABEL = {"memoria": "memória", "ajustes": "ajustes",
                "orfaos": "órfãos", "disco": "disco"}


VERDICT = {health.GREEN: ("Saudável", TOKENS.ok), health.YELLOW: ("Atenção", TOKENS.warning),
           health.RED: ("Crítico", TOKENS.danger), health.UNKNOWN: ("Desconhecido", TOKENS.muted)}


def headroom_pct(snapshot) -> int | None:
    """Smallest free share among memory, swap and the fullest watched tmpfs; None without data."""
    shares = []
    if snapshot.mem is not None and snapshot.mem.mem_total_kb:
        shares.append(snapshot.mem.mem_available_kb / snapshot.mem.mem_total_kb)
    if snapshot.swap_total_kb:
        shares.append(1 - snapshot.swap_used_kb / snapshot.swap_total_kb)
    measured = [v for v in snapshot.tmpfs if v.quality == "ok" and v.total_bytes]
    if measured:
        shares.append(1 - max(v.used_frac for v in measured))
    return round(max(0.0, min(shares)) * 100) if shares else None


def usage_level(used_frac: float, *, warning: float, critical: float) -> str:
    return "crítico" if used_frac >= critical else "atenção" if used_frac >= warning else "ok"


class HealthGauge(QWidget):
    """Ring with the headroom number and the verdict word; static, no animation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(176, 176)
        self.value: int | None = None
        self.verdict, self.color = VERDICT[health.UNKNOWN]
        self.setAccessibleName("Saúde geral")
        self._sync_accessible()

    def set_state(self, value: int | None, level: str) -> None:
        self.value = value
        self.verdict, self.color = VERDICT.get(level, VERDICT[health.UNKNOWN])
        self._sync_accessible()
        self.update()

    def _sync_accessible(self):
        amount = "sem dados" if self.value is None else f"{self.value}% de folga"
        self.setAccessibleDescription(f"{self.verdict}, {amount}")
        self.setToolTip("Menor folga entre memória, swap e temporários; o veredito vem do relatório de saúde")

    def paintEvent(self, event):
        side = min(self.width(), self.height()) - 16
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QPen(QColor(TOKENS.surface_alt), 12)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(rect, 225 * 16, -270 * 16)
        if self.value is not None:
            arc = QPen(QColor(self.color), 12)
            arc.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arc)
            painter.drawArc(rect, 225 * 16, int(-270 * 16 * self.value / 100))
        painter.setPen(QColor(TOKENS.text))
        font = painter.font()
        font.setPointSizeF(font.pointSizeF() * 2.2)
        font.setBold(True)
        painter.setFont(font)
        number = rect.adjusted(0, -side * 0.08, 0, -side * 0.08)
        painter.drawText(number, Qt.AlignmentFlag.AlignCenter, "—" if self.value is None else f"{self.value}%")
        font.setPointSizeF(font.pointSizeF() / 2.2)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(self.color))
        painter.drawText(rect.adjusted(0, side * 0.22, 0, side * 0.22), Qt.AlignmentFlag.AlignCenter,
                         f"{self.verdict} · folga")
        painter.end()


class ResourceCard(QFrame):
    """One resource: big number, bar and a state word (colour is never the only signal)."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.value = QLabel("—")
        self.value.setObjectName("cardValue")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.detail = QLabel("aguardando amostra")
        self.detail.setObjectName("why")
        self.detail.setWordWrap(True)
        self.setAccessibleName(title)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        for widget in (self.title, self.value, self.bar, self.detail):
            layout.addWidget(widget)

    def set_value(self, used_frac: float | None, level: str, detail: str) -> None:
        if used_frac is None:
            self.value.setText("—")
            self.bar.setValue(0)
            self.setProperty("level", "unknown")
        else:
            self.value.setText(f"{used_frac * 100:.0f}%")
            self.bar.setValue(round(used_frac * 100))
            self.setProperty("level", {"ok": "ok", "atenção": "warning", "crítico": "danger"}[level])
        self.detail.setText(detail)
        self.setAccessibleDescription(f"{self.value.text()} · {detail}")
        self.style().unpolish(self)
        self.style().polish(self)


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

        # topo: medidor + veredito + uma ação principal
        self.gauge = HealthGauge()
        self.details.setObjectName("why")
        self.primary_button = QPushButton("Tudo dentro do orçamento")
        self.primary_button.setObjectName("primary")
        self.primary_button.setEnabled(False)
        self.primary_button.setAccessibleName("Ir para a recomendação mais urgente")
        self.primary_button.clicked.connect(self._primary_clicked)
        hero_text = QVBoxLayout()
        hero_text.setSpacing(6)
        hero_text.addStretch(1)
        hero_text.addWidget(self.headline)
        self.verdict_line = QLabel("")
        self.verdict_line.setObjectName("why")
        self.verdict_line.setWordWrap(True)
        hero_text.addWidget(self.verdict_line)
        hero_text.addWidget(self.primary_button, 0, Qt.AlignmentFlag.AlignLeft)
        hero_text.addStretch(1)
        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.addWidget(self.gauge, 0)
        hero_layout.addLayout(hero_text, 1)

        # um cartão por recurso
        self.cards = {key: ResourceCard(title) for key, title in (
            ("memoria", "Memória"), ("cpu", "CPU"), ("swap", "Swap / zram"), ("tmpfs", "Temporários"))}
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, card in enumerate(self.cards.values()):
            grid.addWidget(card, 0, index)

        recommendations = QLabel("Recomendações")
        recommendations.setObjectName("section")
        self.no_recommendations = QLabel("Nenhuma recomendação agora: os recursos estão dentro do orçamento.")
        self.no_recommendations.setObjectName("why")
        activity_title = QLabel("Atividade recente")
        activity_title.setObjectName("section")
        activity = QFrame()
        activity.setObjectName("card")
        activity_layout = QVBoxLayout(activity)
        for widget in (self.last_operation, self.automation_status, self.resources, self.details):
            activity_layout.addWidget(widget)
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        footer.addWidget(self.copy_button, 0)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(hero)
        layout.addLayout(grid)
        layout.addWidget(recommendations)
        layout.addWidget(self.no_recommendations)
        layout.addWidget(holder)
        layout.addWidget(activity_title)
        layout.addWidget(activity)
        layout.addStretch(1)
        layout.addLayout(footer)

    def show_snapshot(self, snapshot, *, orphan_count: int = 0,
                      thumbnails_kb: int | None = None,
                      extra_notes=(), signal=None, last_operation: str = ""):
        signal = signal or title_signal.compute(snapshot, self._thresholds)
        self.headline.setText(signal.text)
        self.details.setText(self._details(snapshot))
        headroom = headroom_pct(snapshot)
        self.gauge.set_state(headroom, signal.level)
        verdict = VERDICT.get(signal.level, VERDICT[health.UNKNOWN])[0]
        self.verdict_line.setText(
            f"{verdict}: menor folga {headroom}% entre memória, swap e temporários." if headroom is not None
            else f"{verdict}: aguardando dados de memória, swap e temporários.")
        self._show_cards(snapshot)
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

    def _show_cards(self, snapshot) -> None:
        cards, t = self.cards, self._thresholds
        if snapshot.mem is None:
            cards["memoria"].set_value(None, "ok", "sem meminfo")
        else:
            total, avail = snapshot.mem.mem_total_kb, snapshot.mem.mem_available_kb
            used = 1 - avail / max(1, total)
            level = ("crítico" if 1 - used < t.red_available_frac else
                     "atenção" if 1 - used < t.yellow_available_frac else "ok")
            cards["memoria"].set_value(used, level, f"{level} · {title_signal.fmt1(avail / title_signal.MB)} GB livres "
                                       f"de {title_signal.fmt1(total / title_signal.MB)} GB")
        if snapshot.cpu_busy_frac is None:
            cards["cpu"].set_value(None, "ok", "delta ainda não disponível")
        else:
            level = usage_level(snapshot.cpu_busy_frac, warning=.75, critical=.95)
            cards["cpu"].set_value(snapshot.cpu_busy_frac, level, f"{level} · {snapshot.cpu_count} cpu(s)")
        if snapshot.swap_total_kb:
            used = snapshot.swap_used_kb / snapshot.swap_total_kb
            level = usage_level(used, warning=.6, critical=.9)
            cards["swap"].set_value(used, level, f"{level} · {title_signal.fmt1(snapshot.swap_used_kb / title_signal.MB)} GB "
                                    f"de {title_signal.fmt1(snapshot.swap_total_kb / title_signal.MB)} GB")
        else:
            cards["swap"].set_value(None, "ok", "sem swap/zram")
        measured = [v for v in snapshot.tmpfs if v.quality == "ok" and v.total_bytes]
        if measured:
            worst = max(measured, key=lambda v: v.used_frac)
            level = usage_level(worst.used_frac, warning=t.tmpfs_yellow_frac, critical=t.tmpfs_red_frac)
            cards["tmpfs"].set_value(worst.used_frac, level, f"{level} · mais cheio: {worst.path}")
        else:
            cards["tmpfs"].set_value(None, "ok", "sem volume observado")

    @Slot()
    def _primary_clicked(self):
        if self.rows:
            self._jump(self.rows[0].target)

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
        self.no_recommendations.setVisible(not rows)
        if rows:
            top = rows[0].suggestion
            self.primary_button.setText(f"Resolver agora: {TARGET_LABEL.get(top.target, 'aba')}")
            self.primary_button.setEnabled(True)
        else:
            self.primary_button.setText("Tudo dentro do orçamento")
            self.primary_button.setEnabled(False)
