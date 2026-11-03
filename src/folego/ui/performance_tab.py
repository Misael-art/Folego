"""Performance mode: apps grouped per unit, rule modes and suggestions.

The tab never acts. It shows which groups host agent work, which are protected
and which are observed, plus the suggestions whose rule condition has held for
the whole wait. Collection (cgroups, cwd, Git lookups, rule tracking) runs on its
own worker and only while the tab is visible, because a hidden view must not
cost CPU. An unreadable rules file disables every suggestion and says why.
"""
import time
from dataclasses import dataclass

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import paths
from ..actions.disk.planner import fmt_bytes
from ..core import perf_model, perf_rules
from .theme import TOKENS

COLUMNS = ("Estado", "App", "Memória", "CPU", "Processos", "Motivo")
STATES = {perf_model.AGENT: ("Agente", "accent"), perf_model.PROTECTED: ("Protegido", "muted"),
          perf_model.OBSERVED: ("Observado", "warning")}
LOADS = {"idle": "ociosos", "interactive": "em uso", "busy": "em build/teste"}
MIN_RSS_KB = 20 * 1024


MODE_NAMES = {perf_rules.OFF: "Desligada", perf_rules.SUGGEST: "Sugerir"}


@dataclass(frozen=True)
class Observation:
    view: perf_model.PerfView
    suggestions: tuple = ()
    policy_error: str = ""


def _observe_factory(rules_path=None):
    from ..core.collector import MetricsCollector
    from ..core.process_protection import snapshot_checker
    collector = MetricsCollector()
    git_cache: dict = {}
    tracker = perf_rules.ConditionTracker()  # touched only by the worker thread

    def observe():
        snapshot = collector.collect()
        view = perf_model.observe(snapshot, git_cache=git_cache, protected_fn=snapshot_checker())
        try:
            modes = perf_rules.load_modes(rules_path or paths.performance_rules_path())
        except perf_rules.PolicyError as exc:
            return Observation(view, (), str(exc))
        return Observation(view, perf_rules.plan(view, snapshot.procs, modes, tracker,
                                                 time.monotonic()))
    return observe


class SuggestionCard(QFrame):
    """One suggestion: what, why, how long it has held and the lever (never applied here)."""

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.title = QLabel(f"{item.title} · {item.label}")
        self.title.setObjectName("cardTitle")
        if item.kind == perf_rules.ADVICE:
            state = "conselho"
        elif item.ready:
            state = "pronta"
        else:
            state = f"observando {item.waited_s:.0f}/{item.need_s:.0f} s"
        self.detail = QLabel(f"{fmt_bytes(item.rss_kb * 1024)} · {item.reason} · {state}")
        self.detail.setWordWrap(True)
        self.action = QLabel(item.action)
        self.action.setObjectName("why")
        self.action.setWordWrap(True)
        self.setProperty("level", "warning" if item.ready else "unknown")
        self.setAccessibleName(self.title.text())
        self.setAccessibleDescription(f"{self.detail.text()} · {item.action}")
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        for widget in (self.title, self.detail, self.action):
            layout.addWidget(widget)


class PerformanceTab(QWidget):
    def __init__(self, *, observe_factory=_observe_factory, interval_s=5.0, rules_path=None,
                 parent=None):
        super().__init__(parent)
        self._observe_factory = observe_factory
        self._interval_s = interval_s
        self._rules_path = rules_path
        self._poller = None
        self.view = None
        self.suggestions = ()
        self.summary = QLabel("Aguardando a primeira observação…")
        self.summary.setWordWrap(True)
        self.notice = QLabel("Somente sugestões: nada é fechado nesta versão.")
        self.notice.setWordWrap(True)
        self.cards = QVBoxLayout()
        self.cards.setSpacing(6)
        self.rules = QGridLayout()
        self.mode_choices = {}
        for row, rule in enumerate(perf_rules.RULES):
            choice = QComboBox()
            for mode in perf_rules.MODES:
                choice.addItem(MODE_NAMES[mode], mode)
            choice.setAccessibleName("Modo da regra " + rule.title)
            choice.currentIndexChanged.connect(lambda _i, r=rule.id: self._mode_changed(r))
            self.mode_choices[rule.id] = choice
            title = QLabel(rule.title)
            title.setToolTip(rule.closer)
            self.rules.addWidget(title, row, 0)
            self.rules.addWidget(choice, row, 1)
        self._load_modes()
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
        layout.addLayout(self.cards)
        layout.addLayout(self.rules)
        layout.addWidget(self.table, 1)

    def _path(self):
        return self._rules_path or paths.performance_rules_path()

    def _load_modes(self):
        try:
            modes = perf_rules.load_modes(self._path())
        except perf_rules.PolicyError as exc:
            self.notice.setText(f"Modo Desempenho desligado: {exc}")
            for choice in self.mode_choices.values():
                choice.setEnabled(False)
            return
        for rule_id, choice in self.mode_choices.items():
            choice.blockSignals(True)
            choice.setCurrentIndex(choice.findData(modes[rule_id]))
            choice.blockSignals(False)

    def _mode_changed(self, rule_id):
        try:
            modes = perf_rules.load_modes(self._path())
            modes[rule_id] = self.mode_choices[rule_id].currentData()
            perf_rules.save_modes(self._path(), modes)
        except (perf_rules.PolicyError, OSError) as exc:
            self.notice.setText(f"Modo não gravado: {exc}")
            self._load_modes()
            return
        if self._poller is not None:
            self._poller.request()

    def showEvent(self, event):
        super().showEvent(event)
        if self._poller is None:
            from .workers import Poller
            self._poller = Poller(collect_fn=self._observe_factory(self._rules_path), interval_s=self._interval_s,
                                  parent=self, offload=True)
            self._poller.snapshot_ready.connect(self.show_observation)
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

    def show_observation(self, observation):
        self.show_view(observation.view)
        if observation.policy_error:
            self.notice.setText(f"Modo Desempenho desligado: {observation.policy_error}")
        else:
            self.notice.setText("Somente sugestões: nada é fechado nesta versão.")
        self.show_suggestions(observation.suggestions)

    def show_suggestions(self, items):
        self.suggestions = tuple(items)
        while self.cards.count():
            widget = self.cards.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        if not items:
            empty = QLabel("Nenhuma sugestão agora.")
            empty.setObjectName("why")
            self.cards.addWidget(empty)
        for item in items:
            self.cards.addWidget(SuggestionCard(item))

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
