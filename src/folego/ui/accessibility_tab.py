"""Input health presentation and explicit requests; no host I/O on the Qt loop."""
import json
import math
import sys
import time

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .tune_jobs import TuneJobs
from .workers import Poller
from ..core.accessibility import LABELS, STALE_SECONDS, ACTION, sample_age
from ..orchestration.models import ActionPlan

WORDS = {"observed": "Configuração observada", "degraded": "Revisão necessária",
         "unavailable": "Indisponível", "unknown": "Desconhecido",
         "unsupported": "Sem backend neste host", "not-observed": "Não observado"}


def access_argv(action, target, confirm):
    command = action.removeprefix("accessibility-")
    argv = [sys.executable, "-m", "folego", "accessibility", command, "--json"]
    if command == "repair":
        argv.extend(["--plan", target])
    elif command == "reconcile":
        argv.append(target)
    if confirm:
        argv.append("--confirmar")
    return argv


class AccessibilityTab(QWidget):
    report_ready = Signal(object)
    options_requested = Signal()
    def __init__(self, *, inspect_fn=None, jobs=None, confirm_fn=None, parent=None):
        super().__init__(parent)
        self.inspect_fn = inspect_fn
        self._jobs = jobs if jobs is not None else TuneJobs(
            parent=self, argv_factory=access_argv, timeout_ms=25000)
        self._confirm = confirm_fn or self._ask
        self._poller = None
        self._report = None
        self._busy = False
        self._pending = ""
        self.summary = QLabel("Entrada: aguardando primeira verificação")
        self.summary.setWordWrap(True)
        self.status = QLabel("Nenhum reparo solicitado. Enumeração não comprova funcionamento físico.")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Resultado da supervisão de acessibilidade")
        self.cards = {}
        grid = QGridLayout()
        for index, (key, label) in enumerate(LABELS.items()):
            card = QFrame()
            card.setObjectName("card")
            box = QVBoxLayout(card)
            title, detail = QLabel(label), QLabel("Desconhecido · aguardando dados")
            detail.setWordWrap(True)
            detail.setAccessibleName(label)
            box.addWidget(title)
            box.addWidget(detail)
            grid.addWidget(card, index // 2, index % 2)
            self.cards[key] = detail
        self.providers = QLabel("Responsáveis e capacidades ainda não observados.")
        self.providers.setWordWrap(True)
        for label in (self.summary, self.status, self.providers, *self.cards.values()):
            label.setTextFormat(Qt.TextFormat.PlainText)
        self.choice = QComboBox()
        self.choice.setAccessibleName("Dispositivo do plano de reparo")
        self.repair_button = QPushButton("Solicitar reparo")
        self.repair_button.setEnabled(False)
        self.repair_button.clicked.connect(self.repair_selected)
        self.verify_button = QPushButton("Verificar agora")
        self.verify_button.clicked.connect(self.refresh)
        self.capture_button = QPushButton("Registrar configuração atual")
        self.capture_button.clicked.connect(lambda: self.configure("capture"))
        self.auto_button = QPushButton("Habilitar automação de entrada")
        self.auto_button.clicked.connect(self.toggle_automatic)
        self.auto_button.setToolTip("Controle próprio de entrada; pausar a coleta de recursos não desliga estes reparos.")
        self.install_button = QPushButton("Opções de início com a sessão")
        self.install_button.clicked.connect(lambda: self.options_requested.emit())
        self.rearm_button = QPushButton("Rearmar após revisão")
        self.rearm_button.setVisible(False)
        self.rearm_button.clicked.connect(lambda: self.configure("rearm"))
        self.reconcile_button = QPushButton("Verificar operação pendente")
        self.reconcile_button.setEnabled(False)
        self.reconcile_button.setVisible(False)
        self.reconcile_button.clicked.connect(self.reconcile)
        controls = QHBoxLayout()
        controls.addWidget(self.choice, 1)
        controls.addWidget(self.repair_button)
        controls.addWidget(self.reconcile_button)
        settings = QGridLayout()
        settings.addWidget(self.verify_button, 0, 0)
        settings.addWidget(self.capture_button, 0, 1)
        settings.addWidget(self.auto_button, 1, 0, 1, 2)
        settings.addWidget(self.install_button, 2, 0, 1, 2)
        settings.addWidget(self.rearm_button, 3, 0, 1, 2)
        content = QWidget()
        box = QVBoxLayout(content)
        box.addWidget(self.summary)
        box.addLayout(grid)
        box.addWidget(self.providers)
        box.addLayout(controls)
        box.addLayout(settings)
        box.addWidget(self.status)
        box.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        self._freshness = QTimer(self)
        self._freshness.setInterval(1000)
        self._freshness.timeout.connect(self.check_freshness)
        self._freshness.start()

    def start(self):
        if self._poller is None:
            if self.inspect_fn is None:
                from ..actions.accessibility import Supervisor
                self.inspect_fn = Supervisor().inspect
            self._poller = Poller(self.inspect_fn, interval_s=10, offload=True, parent=self)
            self._poller.snapshot_ready.connect(self.show_report)
            self._poller.error.connect(self.show_error)
            self._poller.start()
        self._poller.request()

    def refresh(self):
        self.start()

    def show_error(self, error):
        self._report = None
        for card in self.cards.values():
            card.setText("Desconhecido · coleta indisponível")
        self.summary.setText("Entrada: coleta indisponível")
        self.repair_button.setEnabled(False)
        self.status.setText("verificação indisponível: " + str(error))
        self.report_ready.emit({"state": "unknown", "blockers": [str(error)]})

    def show_report(self, report):
        if (not isinstance(report, dict) or type(report.get("schema")) is not int or report.get("schema") != 1
                or type(report.get("mono")) not in (int, float) or not math.isfinite(report["mono"])
                or not isinstance(report.get("cards"), list) or len(report["cards"]) > 32
                or any(not isinstance(row, dict) or not all(isinstance(row.get(key), str)
                           for key in ("key", "state", "detail")) for row in report["cards"])
                or not isinstance(report.get("plans", []), list)
                or not isinstance(report.get("policy", {}), dict)
                or not isinstance(report.get("watcher", {}), dict)
                or not isinstance(report.get("blockers", []), list)
                or not all(isinstance(value, str) for value in report.get("blockers", []))
                or not isinstance(report.get("pending_operations", []), list)
                or not all(isinstance(value, str) for value in report.get("pending_operations", []))):
            self.show_error("resposta desconhecida; nenhuma ação autorizada")
            return
        try:
            if len(report.get("plans", [])) > 64:
                raise ValueError("planos excedem orçamento")
            for plan in report.get("plans", []):
                if ActionPlan.from_dict(plan).action != ACTION:
                    raise ValueError("plano de outro domínio")
        except (ValueError, TypeError):
            self.show_error("plano ilegível; nenhuma ação autorizada")
            return
        self._report = report
        for card in self.cards.values():
            card.setText("Desconhecido · fonte não declarada")
        for row in report["cards"]:
            if row["key"] in self.cards:
                self.cards[row["key"]].setText(f"{WORDS.get(row['state'], 'Desconhecido')} · {row['detail']}")
        enabled = report.get("policy", {}).get("enabled") is True
        self.summary.setText(f"Entrada: {report.get('backend', 'desconhecido')} · automação de entrada "
                             + ("habilitada" if enabled else "desabilitada")
                             + f" · {report.get('baseline_count', 0)} dispositivo(s) registrado(s) · monitor residente: "
                             + ("ciclo recente" if report.get("watcher", {}).get("state") == "observed" else "sem sinal recente"))
        self.auto_button.setText("Desabilitar automação de entrada" if enabled else "Habilitar automação de entrada")
        self.install_button.setEnabled(not self._busy)
        blockers = report.get("blockers", [])
        self.providers.setText("Aguardando: " + "; ".join(blockers) if blockers else
                               "Backend nativo disponível conforme capacidades; sem responsável externo bloqueando.")
        alerts = report.get("alerts", [])
        if isinstance(alerts, list) and all(isinstance(value, str) for value in alerts):
            self.providers.setText(self.providers.text() + ("\n" + "\n".join(alerts) if alerts else ""))
        self.choice.clear()
        for plan in report.get("plans", []):
            self.choice.addItem(plan["params"]["name"], plan)
        pending = report.get("pending_operations", [])
        if pending:
            self._pending = pending[0]
        self.repair_button.setEnabled(bool(self.choice.count()) and not self._busy and not self._pending)
        self.reconcile_button.setEnabled(bool(self._pending) and not self._busy)
        self.reconcile_button.setVisible(bool(self._pending))
        if self._pending:
            self.status.setText("desconhecido: operação " + self._pending + " · não repetir antes de verificar")
        circuit = report.get("policy", {}).get("circuit", "")
        self.rearm_button.setVisible(bool(circuit))
        self.rearm_button.setEnabled(not self._busy and not self._pending)
        if circuit and not self._pending:
            self.status.setText("Reparos suspensos: " + str(circuit))
        self.check_freshness()
        if self._report is not None:
            self.report_ready.emit(report)

    def check_freshness(self):
        if self._report is not None and (self._report.get("mono", 0) <= 0 or
                not 0 <= sample_age(self._report) <= STALE_SECONDS):
            self.show_error("amostra antiga; aguarde nova leitura")

    def repair_selected(self):
        self.check_freshness()
        plan = self.choice.currentData()
        if self._report is None or self._busy or self._pending or not plan:
            return
        if not self._confirm("Reabilitar entrada", "Reabilitar somente " + plan["params"]["name"] +
                             " no compositor? Não altera driver, perfis de jogo ou áudio. Teste físico será necessário."):
            return
        self._pending = plan["operation_id"]
        self._run("repair", json.dumps(plan), confirm=True)

    def configure(self, command):
        if self._busy:
            return
        messages = {
            "enable": ("Proteger entrada", "O monitor residente poderá reabilitar dispositivos registrados como habilitados. "
                       "Desligue esta política antes de desabilitar um deles intencionalmente. "
                       "Outros responsáveis e estados desconhecidos bloqueiam o reparo. Não altera áudio, drivers ou perfis de jogo."),
            "disable": ("Pausar reparos de entrada", "Desabilitar os reparos automáticos de entrada? A observação pode continuar."),
            "capture": ("Registrar configuração", "Registrar os dispositivos identificados e habilitados como configuração a preservar? "
                        "Leituras incompletas ou recursos ocupados serão recusados. O funcionamento físico ainda precisa de teste."),
            "install": ("Ativar monitor no login", "Criar e iniciar o monitor do Fôlego na sessão do usuário, "
                        "inclusive após fechar a janela? Ele seguirá a política de entrada e não atua na tela de login do sistema."),
            "rearm": ("Rearmar após revisão", "Rearmar o limite de reparos após investigar a causa? "
                      "O estado habilitado e a ausência de operações pendentes serão verificados antes de retomar."),
        }
        if command in messages and self._confirm(*messages[command]):
            self._run(command, "", confirm=True)

    def toggle_automatic(self):
        enabled = self._report and self._report.get("policy", {}).get("enabled") is True
        self.configure("disable" if enabled else "enable")

    def reconcile(self):
        if self._pending and not self._busy:
            self._run("reconcile", self._pending)

    def _run(self, command, target, *, confirm=False):
        self._busy = True
        self.repair_button.setEnabled(False)
        self.reconcile_button.setEnabled(False)
        self._jobs.run("accessibility-" + command, target, confirm=confirm, done=self.completed)

    def completed(self, payload):
        self._busy = False
        payload = payload or {}
        known = payload.get("outcome") in ("sucesso", "parcial", "recusa", "falha", "cancelamento")
        wrong_id = self._pending and payload.get("operation_id") not in (None, "", self._pending)
        if not known or wrong_id:
            self.status.setText("desconhecido · " + str(payload.get("reason", "resposta ausente")) +
                                " · operação " + self._pending + " · não repetir")
            self.reconcile_button.setEnabled(bool(self._pending))
            self.reconcile_button.setVisible(bool(self._pending))
            return
        if payload.get("operation_id") == self._pending or payload.get("outcome") == "recusa":
            self._pending = ""
            self.reconcile_button.setVisible(False)
        self.status.setText(str(payload.get("outcome", "recusa")) + " · " + str(payload.get("reason", "política atualizada")))
        self.refresh()

    def stop(self):
        self._freshness.stop()
        if self._poller:
            self._poller.stop()
        self._jobs.shutdown()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)

    def _ask(self, title, text):
        return QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
