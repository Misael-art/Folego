"""Performance mode: apps grouped per unit, rule modes and suggestions.

The tab never acts. It shows which groups host agent work, which are protected
and which are observed, plus the suggestions whose rule condition has held for
the whole wait. Collection (cgroups, cwd, Git lookups, rule tracking) runs on its
own worker and only while the tab is visible, because a hidden view must not
cost CPU. An unreadable rules file disables every suggestion and says why.
"""
import sys
import time
from dataclasses import dataclass

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import paths
from ..actions.disk.planner import fmt_bytes
from ..core import perf_auto, perf_model, perf_rules
from .theme import TOKENS

COLUMNS = ("Estado", "App", "Memória", "CPU", "Processos", "Motivo")
STATES = {perf_model.AGENT: ("Agente", "accent"), perf_model.PROTECTED: ("Protegido", "muted"),
          perf_model.OBSERVED: ("Observado", "warning")}
LOADS = {"idle": "ociosos", "interactive": "em uso", "busy": "em build/teste"}
MIN_RSS_KB = 20 * 1024


MODE_NAMES = {perf_rules.OFF: "Desligada", perf_rules.SUGGEST: "Sugerir",
              perf_rules.ASSISTED: "Assistido", perf_rules.AUTOMATIC: "Automático"}
CLOSE_TIMEOUT_MS = 60_000  # bounded follow-up of 20 s plus two observations


SUBCOMMANDS = {"performance-close": "close", "performance-snooze": "snooze",
               "performance-protect": "protect", "performance-resume": "resume"}


def argv_for(acao: str, target: str = "", confirm: bool = False) -> list:
    rule, _, unit = target.partition("\t")
    argv = [sys.executable, "-m", "folego", "performance", SUBCOMMANDS[acao]]
    if rule:
        argv.extend([rule, "--unit", unit])
    argv.append("--json")
    if confirm:
        argv.append("--confirmar")
    return argv


@dataclass(frozen=True)
class Observation:
    view: perf_model.PerfView
    suggestions: tuple = ()
    policy_error: str = ""
    auto: dict | None = None        # automatic state file, None when unreadable
    auto_error: str = ""


def _auto_state():
    from ..actions.performance.auto import state_store
    try:
        return state_store().read().to_dict(), ""
    except perf_auto.AutoStateError as exc:
        return None, str(exc)


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
        auto, auto_error = _auto_state()
        return Observation(view, perf_rules.plan(view, snapshot.procs, modes, tracker,
                                                 time.monotonic()), auto=auto, auto_error=auto_error)
    return observe


class SuggestionCard(QFrame):
    """One suggestion: what, why, how long it has held and the lever (never applied here)."""

    def __init__(self, item, on_close=None, on_snooze=None, on_protect=None, waiting="", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.item = item
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
        if waiting:
            self.waiting = QLabel("Automático: " + waiting)
            self.waiting.setObjectName("why")
            self.waiting.setWordWrap(True)
            layout.addWidget(self.waiting)
        self.close_button = self.snooze_button = self.protect_button = None
        buttons = QHBoxLayout()
        if item.closable and on_close is not None:
            self.close_button = QPushButton("Fechar " + item.label)
            self.close_button.setAccessibleName(f"Fechar {item.label}: {item.action}")
            self.close_button.clicked.connect(lambda: on_close(item))
            buttons.addWidget(self.close_button)
        if item.mode == perf_rules.AUTOMATIC and item.kind == perf_rules.CLOSE and on_snooze is not None:
            self.snooze_button = QPushButton("Adiar 30 min")
            self.snooze_button.setAccessibleName(f"Adiar o fechamento automático de {item.label}")
            self.snooze_button.clicked.connect(lambda: on_snooze(item))
            self.protect_button = QPushButton("Proteger sempre")
            self.protect_button.setAccessibleName(f"Nunca fechar {item.label}")
            self.protect_button.clicked.connect(lambda: on_protect(item))
            buttons.addWidget(self.snooze_button)
            buttons.addWidget(self.protect_button)
        if buttons.count():
            buttons.addStretch(1)
            layout.addLayout(buttons)


class PerformanceTab(QWidget):
    def __init__(self, *, observe_factory=_observe_factory, interval_s=5.0, rules_path=None,
                 jobs=None, confirm_fn=None, parent=None):
        super().__init__(parent)
        self._jobs = jobs
        self._confirm = confirm_fn or self._ask
        self.closing = ""
        self._observe_factory = observe_factory
        self._interval_s = interval_s
        self._rules_path = rules_path
        self._poller = None
        self.view = None
        self.suggestions = ()
        self.auto = None
        self._waiting = {}
        self.summary = QLabel("Aguardando a primeira observação…")
        self.summary.setWordWrap(True)
        self.notice = QLabel("")
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
        self.auto_status = QLabel("")
        self.auto_status.setWordWrap(True)
        self.resume_button = QPushButton("Retomar automático")
        self.resume_button.setAccessibleName("Fechar o disjuntor do Modo Desempenho automático")
        self.resume_button.clicked.connect(self.request_resume)
        self.resume_button.hide()
        auto_row = QHBoxLayout()
        auto_row.addWidget(self.auto_status, 1)
        auto_row.addWidget(self.resume_button)
        layout.addLayout(auto_row)
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
            self.notice.setText(self._idle_notice())
        self.show_auto(observation.auto, observation.auto_error)
        self.show_suggestions(observation.suggestions)

    def show_auto(self, auto, error=""):
        self.auto = auto
        self._waiting = {}
        if auto is None:
            self.auto_status.setText("Automático desligado: " + (error or "estado indisponível"))
            self.resume_button.hide()
            return
        last = auto.get("last") or {}
        self._waiting = {(w["rule"], w["unit"]): w["why"] for w in last.get("waiting", [])}
        breaker = auto.get("breaker", "")
        history = auto.get("history", [])
        done = f" · último: {history[-1]['label']} ({history[-1]['outcome']})" if history else ""
        if breaker:
            self.auto_status.setText("Automático pausado pelo disjuntor: " + breaker + done)
        elif last:
            trigger = last.get("trigger") or "sem pressão no host"
            self.auto_status.setText(f"Automático ativo · gatilho: {trigger}{done}")
        else:
            self.auto_status.setText("Automático sem executor: instale com folego performance install --confirmar"
                                     + done)
        self.resume_button.setVisible(bool(breaker))

    def request_resume(self):
        if self._jobs is None or self.closing:
            return
        if self._confirm("Retomar automático?", "Fechar o disjuntor e voltar a avaliar fechamentos "
                                                "automáticos no próximo ciclo?"):
            self._run("performance-resume", "", "o disjuntor")

    def request_snooze(self, item):
        if self._jobs is not None and not self.closing:
            self._run("performance-snooze", item.rule + "\t" + item.unit, item.label)

    def request_protect(self, item):
        if self._jobs is None or self.closing:
            return
        if self._confirm("Proteger " + item.label + " sempre?",
                         f"Criar uma exclusão permanente para {item.label}. O Modo Desempenho nunca "
                         "mais o sugerirá nem fechará; desfaça em órfãos › proteções."):
            self._run("performance-protect", item.rule + "\t" + item.unit, item.label, confirm=True)

    def _run(self, acao, target, label, confirm=False):
        self.closing = label
        self.notice.setText(self._idle_notice())
        self.show_suggestions(self.suggestions)
        self._jobs.run(acao, target, confirm=confirm, done=self._closed)

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
            busy = bool(self.closing)
            card = SuggestionCard(item, on_close=None if busy else self.request_close,
                                  on_snooze=None if busy else self.request_snooze,
                                  on_protect=self.request_protect,
                                  waiting=self._waiting.get((item.rule, item.unit), ""))
            self.cards.addWidget(card)

    def _idle_notice(self):
        if self.closing:
            return f"Aplicando em {self.closing}…"
        return ("Fechar exige espera completa: Assistido pede o seu clique; Automático só age "
                "sob pressão, após aviso e carência, dentro do orçamento.")

    @staticmethod
    def _ask(title, text):
        from .confirmation import confirm_text
        return confirm_text("Fôlego — " + title, text)

    def request_close(self, item):
        if self._jobs is None or self.closing:
            return
        text = (f"{item.action}.\n\n{item.label} · {fmt_bytes(item.rss_kb * 1024)} · {item.reason}.\n"
                "O Fôlego revalida agentes, exclusões e a condição antes de pedir, e confere a saída.")
        if not self._confirm("Fechar " + item.label + "?", text):
            return
        self._run("performance-close", item.rule + "\t" + item.unit, item.label, confirm=True)

    def _closed(self, payload):
        label, self.closing = self.closing, ""
        outcome = payload.get("outcome", "desconhecido")
        self.notice.setText(f"{label}: {outcome} — {payload.get('reason', 'sem resposta')}")
        self.show_suggestions(self.suggestions)
        if self._poller is not None:
            self._poller.request()

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
            using = view.in_use.get(group.unit)
            values = (label, group.label, fmt_bytes(group.rss_kb * 1024), cpu,
                      str(group.procs), f"{group.reason} · em uso: {using}" if using else group.reason)
            for col, text in enumerate(values):
                item = self.table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row, col, item)
                item.setText(text)
                item.setToolTip(group.unit if col == 1 else "")
            self.table.item(row, 0).setForeground(QColor(getattr(TOKENS, token)))
