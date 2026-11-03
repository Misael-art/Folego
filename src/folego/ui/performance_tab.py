"""Performance mode, increment 1: read-only view of apps grouped per unit.

The tab never acts. It shows which groups host agent work, which are protected
by class and which are merely observed, so the later rules have visible ground.
Collection (cgroups, cwd, Git lookups) runs on its own worker and only while the
tab is visible, because a hidden view must not cost CPU.
"""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..actions.disk.planner import fmt_bytes
from ..core import perf_model
from .theme import TOKENS

COLUMNS = ("Estado", "App", "Memória", "CPU", "Processos", "Motivo")
STATES = {perf_model.AGENT: ("Agente", "accent"), perf_model.PROTECTED: ("Protegido", "muted"),
          perf_model.OBSERVED: ("Observado", "warning")}
LOADS = {"idle": "ociosos", "interactive": "em uso", "busy": "em build/teste"}
MIN_RSS_KB = 20 * 1024


def _observe_factory():
    from ..core.collector import MetricsCollector
    collector = MetricsCollector()
    git_cache: dict = {}
    return lambda: perf_model.observe(collector.collect(), git_cache=git_cache)


class PerformanceTab(QWidget):
    def __init__(self, *, observe_factory=_observe_factory, interval_s=5.0, parent=None):
        super().__init__(parent)
        self._observe_factory = observe_factory
        self._interval_s = interval_s
        self._poller = None
        self.view = None
        self.summary = QLabel("Aguardando a primeira observação…")
        self.summary.setWordWrap(True)
        self.notice = QLabel("Somente observação: nenhuma regra está ativa e nada é fechado.")
        self.notice.setWordWrap(True)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.notice)
        layout.addWidget(self.table, 1)

    def showEvent(self, event):
        super().showEvent(event)
        if self._poller is None:
            from .workers import Poller
            self._poller = Poller(collect_fn=self._observe_factory(), interval_s=self._interval_s,
                                  parent=self, offload=True)
            self._poller.snapshot_ready.connect(self.show_view)
            self._poller.error.connect(self.show_error)
            self._poller.start()
            self._poller.request()
        else:
            self._poller.resume()

    def hideEvent(self, event):
        if self._poller is not None:
            self._poller.pause()
        super().hideEvent(event)

    def shutdown(self):
        if self._poller is not None:
            self._poller.stop()
            self._poller = None

    def show_error(self, message):
        self.summary.setText("Observação indisponível: " + message)

    def show_view(self, view):
        self.view = view
        act = view.activity
        avail = fmt_bytes(view.mem_available_kb * 1024) if view.mem_available_kb is not None else "?"
        psi = f"{view.pressure.some_avg60:.2f}%" if view.pressure else "indisponível"
        self.summary.setText(
            f"Agentes {LOADS.get(act.load, act.load)} · {len(act.projects)} projeto(s) protegido(s) · "
            f"RAM disponível {avail} · pressão de memória (60 s) {psi} · "
            f"observado sem agente {fmt_bytes(view.reclaimable_kb() * 1024)}")
        rows = [g for g in view.groups if g.rss_kb >= MIN_RSS_KB]
        self.table.setRowCount(len(rows))
        for row, group in enumerate(rows):
            label, token = STATES[group.state]
            cpu = "?" if group.cpu_frac is None else f"{group.cpu_frac:.0f}%"
            values = (label, group.label, fmt_bytes(group.rss_kb * 1024), cpu,
                      str(group.procs), group.reason)
            for col, text in enumerate(values):
                item = self.table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row, col, item)
                item.setText(text)
                item.setToolTip(group.unit if col == 1 else "")
            self.table.item(row, 0).setForeground(QColor(getattr(TOKENS, token)))
