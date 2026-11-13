"""Input health presentation and explicit requests; no host I/O on the Qt loop."""
import json
import math
import sys
import time

from PySide6.QtCore import QTimer, Qt, Signal, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .tune_jobs import TuneJobs
from .workers import Poller
from .theme import background, themed_style, TOKENS
from ..core.accessibility import LABELS, STALE_SECONDS, ACTION, sample_age, recovery_scope
from ..orchestration.models import ActionPlan

WORDS = {"observed": "Configuração observada", "degraded": "Revisão necessária",
         "unavailable": "Indisponível", "unknown": "Desconhecido",
         "unsupported": "Sem backend neste host", "not-observed": "Não observado"}
NAMES = {"keyboard": "Teclado físico", "pointer": "Mouse / ponteiro", "touchpad": "Trackpads",
         "touch": "Tela de toque", "gamepad": "Controles", "virtual-keyboard": "Teclado virtual",
         "audio": "Saída de áudio", "microphone": "Microfone"}
ICONS = {"keyboard": "input-keyboard", "pointer": "input-mouse", "touchpad": "input-touchpad",
         "touch": "input-touchscreen", "gamepad": "input-gaming", "virtual-keyboard": "input-keyboard-virtual",
         "audio": "audio-speakers", "microphone": "audio-input-microphone"}


class CapabilityButton(QPushButton):
    """A whole card is a real keyboard-accessible button, with wrapping labels."""
    def __init__(self, key):
        super().__init__()
        self.setObjectName("capabilityButton")
        self.setMinimumHeight(82)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAccessibleName(NAMES[key] + ": habilitar e verificar")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        themed_style(self, lambda: f'''
            QPushButton#capabilityButton {{ background: {background(TOKENS.surface)}; border: 2px solid {TOKENS.border}; border-radius: 12px; }}
            QPushButton#capabilityButton:hover {{ background: {background(TOKENS.surface_alt)}; }}
            QPushButton#capabilityButton[recovery="ready"] {{ border-color: {TOKENS.ok}; }}
            QPushButton#capabilityButton[recovery="attention"], QPushButton#capabilityButton[recovery="busy"] {{ border-color: {TOKENS.warning}; }}
            QPushButton#capabilityButton:focus {{ border-width: 3px; background: {background(TOKENS.surface_alt)}; }}
            QPushButton#capabilityButton QLabel {{ background: transparent; border: none; }}
        ''')
        icon = QLabel()
        icon.setPixmap(QIcon.fromTheme(ICONS[key]).pixmap(22, 22))
        title = QLabel(NAMES[key])
        self.detail = QLabel("Clique para habilitar e verificar")
        self.detail.setWordWrap(True)
        for label in (icon, title, self.detail):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setTextFormat(Qt.TextFormat.PlainText)
        header = QHBoxLayout()
        header.addWidget(icon)
        header.addWidget(title, 1)
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(4)
        box.addLayout(header)
        box.addWidget(self.detail)
        self.set_state("neutral")

    def set_state(self, state):
        self.setProperty("recovery", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def setText(self, text):
        self.detail.setText(text)
        self.setAccessibleDescription(text)

    def text(self):
        return self.detail.text()

    def sizeHint(self):
        return self.layout().sizeHint().expandedTo(QSize(180, 82))


def access_argv(action, target, confirm):
    command = action.removeprefix("accessibility-")
    argv = [sys.executable, "-m", "folego", "accessibility", command, "--json"]
    if command in ("repair", "activate", "save-profile"):
        argv.extend(["--plan", target])
    elif command == "activation-plan":
        value = json.loads(target)
        argv.append(value["capability"])
        if value.get("save"):
            argv.append("--save-profile")
    elif command in ('reconcile', 'profile-rearm'):
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
            parent=self, argv_factory=access_argv, timeout_ms=180000)
        self._confirm = confirm_fn or self._ask
        self._poller = None
        self._report = None
        self._busy = False
        self._pending = ""
        self._emergency_previous = ""
        self._stopped = False
        self._verifying = False
        self._active_scope = []
        self._verified = {}
        self._pending_capabilities = {}
        self.summary = QLabel("Entrada: aguardando primeira verificação")
        self.summary.setWordWrap(True)
        self.status = QLabel("Clique em uma capacidade ou em Habilitar tudo. Verde: configuração verificada no sistema; teste físico pendente.")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Resultado da supervisão de acessibilidade")
        self.cards = {}
        grid = QGridLayout()
        for index, key in enumerate(LABELS):
            card = CapabilityButton(key)
            card.clicked.connect(lambda checked=False, capability=key: self.activate(capability))
            grid.addWidget(card, index // 2, index % 2)
            self.cards[key] = card
        self.providers = QLabel("Responsáveis e capacidades ainda não observados.")
        self.providers.setWordWrap(True)
        for label in (self.summary, self.status, self.providers):
            label.setTextFormat(Qt.TextFormat.PlainText)
        self.choice = QComboBox()
        self.choice.setAccessibleName("Dispositivo do plano de reparo")
        self.repair_button = QPushButton("Solicitar reparo")
        self.repair_button.setEnabled(False)
        self.repair_button.clicked.connect(self.repair_selected)
        self.verify_button = QPushButton("Verificar agora")
        self.verify_button.clicked.connect(self.refresh)
        self.enable_all_button = QPushButton("Habilitar tudo")
        self.enable_all_button.setObjectName("enableAllAccessibility")
        self.enable_all_button.setMinimumHeight(48)
        self.enable_all_button.setAccessibleDescription("Tentar habilitar todas as capacidades, com resultado separado e sem desabilitar entradas")
        self.enable_all_button.clicked.connect(lambda: self.activate("all"))
        self.capture_button = QPushButton("Registrar configuração para preservar")
        self.capture_button.clicked.connect(self.save_profile)
        self.auto_button = QPushButton("Habilitar automação de entrada")
        self.auto_button.clicked.connect(self.toggle_automatic)
        self.auto_button.setToolTip("Controle próprio de entrada; pausar a coleta de recursos não desliga estes reparos.")
        self.install_button = QPushButton("Opções de início com a sessão")
        self.install_button.clicked.connect(lambda: self.options_requested.emit())
        self.rearm_button = QPushButton("Rearmar após revisão")
        self.rearm_button.setVisible(False)
        self.rearm_button.clicked.connect(lambda: self.configure("rearm"))
        self.audio_reprobe_choice = QCheckBox('Reenumerar áudio automaticamente após falha conhecida')
        self.audio_reprobe_choice.clicked.connect(lambda checked: self.configure(
            'audio-reprobe-enable' if checked else 'audio-reprobe-disable'))
        self.audio_reprobe_choice.setToolTip('Revalida WirePlumber e a preferência saudável antes do reparo, com orçamento e disjuntor.')
        self.reconcile_button = QPushButton("Verificar operação pendente")
        self.reconcile_button.setEnabled(False)
        self.reconcile_button.setVisible(False)
        self.reconcile_button.clicked.connect(self.reconcile)
        self.pending_choice = QComboBox()
        self.pending_choice.setMinimumContentsLength(20)
        self.pending_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.pending_choice.setVisible(False)
        self.pending_choice.currentIndexChanged.connect(self._select_pending)
        self.profile_rearm_buttons = {}
        for key in ('touchpad', 'microphone'):
            button = QPushButton('Rearmar guarda de ' + NAMES[key].lower())
            button.setVisible(False)
            button.clicked.connect(lambda checked=False, key=key: self.rearm_profile(key))
            self.profile_rearm_buttons[key] = button
        controls = QHBoxLayout()
        controls.addWidget(self.choice, 1)
        controls.addWidget(self.repair_button)
        self.native_controls = QWidget()
        self.native_controls.setLayout(controls)
        self.native_controls.setVisible(False)
        settings = QGridLayout()
        settings.addWidget(self.capture_button, 0, 0)
        settings.addWidget(self.auto_button, 0, 1)
        settings.addWidget(self.install_button, 1, 1)
        settings.addWidget(self.rearm_button, 1, 0)
        settings.addWidget(self.audio_reprobe_choice, 2, 0, 1, 2)
        settings.addWidget(self.pending_choice, 3, 0, 1, 2)
        for column, button in enumerate(self.profile_rearm_buttons.values()):
            settings.addWidget(button, 4, column)
        for button in (self.verify_button, self.capture_button, self.auto_button, self.install_button):
            button.setMinimumHeight(38)
        content = QWidget()
        box = QVBoxLayout(content)
        box.addLayout(grid)
        box.addWidget(self.providers)
        self.operation_details = QLabel("")
        self.operation_details.setWordWrap(True)
        self.operation_details.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(self.operation_details)
        box.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.status)
        self.keyboard_test = QLineEdit()
        self.keyboard_test.setPlaceholderText("Campo opcional para testar o teclado; o texto não é registrado")
        self.keyboard_test.setAccessibleName("Teste opcional de digitação, sem registro")
        self.keyboard_test.setInputMethodHints(Qt.InputMethodHint.ImhNoPredictiveText | Qt.InputMethodHint.ImhSensitiveData)
        self.keyboard_test.setVisible(False)
        layout.addWidget(self.keyboard_test)
        verification = QHBoxLayout()
        verification.addWidget(self.summary, 1)
        verification.addWidget(self.verify_button)
        verification.addWidget(self.enable_all_button)
        layout.addLayout(verification)
        layout.addWidget(scroll)
        self.scroll = scroll
        layout.addWidget(self.native_controls)
        layout.addWidget(self.reconcile_button)
        layout.addLayout(settings)
        self._freshness = QTimer(self)
        self._freshness.setInterval(1000)
        self._freshness.timeout.connect(self.check_freshness)
        self._freshness.start()

    def start(self):
        if self._stopped:
            return
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
        if self._stopped:
            return
        self._verifying = True
        self.status.setText("Verificando dispositivos e responsáveis… o resumo aparecerá aqui.")
        self.start()

    def show_error(self, error):
        if self._stopped:
            return
        self._report = None
        self._verified.clear()
        for card in self.cards.values():
            card.setText("Desconhecido · coleta indisponível")
            card.set_state("attention")
        self.summary.setText("Entrada: coleta indisponível")
        self.repair_button.setEnabled(False)
        self.status.setText("verificação indisponível: " + str(error))
        self.report_ready.emit({"state": "unknown", "blockers": [str(error)]})

    def show_report(self, report):
        if self._stopped:
            return
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
            card.set_state("neutral")
        for row in report["cards"]:
            if row["key"] in self.cards:
                card = self.cards[row["key"]]
                card.setToolTip(row["detail"])
                proof = self._verified.get(row["key"])
                context = (report.get("boot_id"), report.get("service_owner"))
                if row["state"] == "observed" and proof and proof["ready"] and proof.get("context") == context:
                    card.setText("Habilitado no sistema · teste físico pendente")
                    card.set_state("ready")
                elif row["key"] in report.get("desktop_profiles", {}):
                    card.setText(row["detail"])
                    card.set_state("attention" if row["state"] != "observed" else "neutral")
                elif proof or row["state"] in ("degraded", "unknown", "unavailable", "unsupported", "not-observed"):
                    card.setText(f"{WORDS.get(row['state'], 'Desconhecido')} · clique para tentar reparar")
                    card.set_state("attention")
                else:
                    card.setText("Configuração observada · clique para habilitar e verificar")
        enabled = report.get("policy", {}).get("enabled") is True
        self.summary.setText(f"{report.get('backend', 'desconhecido')} · proteção de entrada e perfis "
                             + ("habilitada" if enabled else "desabilitada")
                             + f" · {report.get('baseline_count', 0)} dispositivo(s) registrado(s) · monitor residente: "
                             + ("ciclo recente" if report.get("watcher", {}).get("state") == "observed" else "sem sinal recente"))
        self.auto_button.setText("Desabilitar supervisão" if enabled else "Habilitar supervisão")
        self.install_button.setEnabled(not self._busy)
        blockers = report.get("blockers", [])
        self.providers.setText("Entrada KWin aguardando: " + "; ".join(blockers) +
                               "\nSteam/microfone têm guarda independente, indicada nos cartões." if blockers else
                               "Backend nativo disponível conforme capacidades; sem responsável externo bloqueando.")
        alerts = report.get("alerts", [])
        if isinstance(alerts, list) and all(isinstance(value, str) for value in alerts):
            self.providers.setText(self.providers.text() + ("\n" + "\n".join(alerts) if alerts else ""))
        self.choice.clear()
        for plan in report.get("plans", []):
            self.choice.addItem(plan["params"]["name"], plan)
        self.native_controls.setVisible(bool(self.choice.count()))
        pending = report.get("pending_operations", [])
        scopes = report.get('pending_capabilities', {})
        self._pending_capabilities = {
            key: set(scopes[key]) if isinstance(scopes, dict) and
            isinstance(scopes.get(key), list) and scopes[key] and
            all(isinstance(value, str) and value in LABELS for value in scopes[key]) else set(LABELS)
            for key in pending}
        self.audio_reprobe_choice.setChecked(report.get('policy', {}).get('audio_reprobe_enabled') is True)
        if pending and not self._busy:
            self._pending = self._pending if self._pending in pending else pending[0]
        self.pending_choice.blockSignals(True)
        self.pending_choice.clear()
        for operation_id, scope in self._pending_capabilities.items():
            self.pending_choice.addItem(operation_id + ' · ' + ', '.join(NAMES[key] for key in sorted(scope)), operation_id)
        self.pending_choice.setCurrentIndex(self.pending_choice.findData(self._pending))
        self.pending_choice.blockSignals(False)
        self.pending_choice.setVisible(len(pending) > 1)
        circuits = report.get('profile_guard', {}).get('circuit', {})
        for key, button in self.profile_rearm_buttons.items():
            button.setVisible(bool(circuits.get(key)))
            button.setToolTip(str(circuits.get(key, '')))
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
        if self._verifying and not self._pending and not self._busy:
            self._verifying = False
            counts = {state: sum(r["state"] == state for r in report["cards"]) for state in ("observed", "degraded", "unavailable", "unknown")}
            self.status.setText(time.strftime("Verificado às %H:%M:%S") +
                f" · {counts['observed']} configurações observadas · {len(report['cards']) - counts['observed']} precisam de atenção" +
                (". " + "; ".join(blockers) if blockers else ". Clique em uma capacidade para habilitar e verificar."))
        self._update_actions()
        self.check_freshness()
        if self._report is not None:
            self.report_ready.emit(report)

    def _update_actions(self):
        allowed = not self._busy and not self._stopped
        self.enable_all_button.setEnabled(allowed)
        self.capture_button.setEnabled(allowed and not self._pending)
        self.audio_reprobe_choice.setEnabled(allowed)
        self.pending_choice.setEnabled(allowed)
        for key, button in self.profile_rearm_buttons.items():
            button.setEnabled(allowed and not self._capability_pending(key))
        for key, card in self.cards.items():
            card.setEnabled(allowed and not self._capability_pending(key))

    def _capability_pending(self, key):
        if key in ('virtual-keyboard', 'all'):
            return False
        pending = dict(self._pending_capabilities)
        if self._pending and self._pending not in pending:
            pending[self._pending] = set(self._active_scope) or set(LABELS)
        return any(key in scope for scope in pending.values())

    def activate(self, capability, *, save=False):
        if self._busy or self._capability_pending(capability) or self._stopped:
            return
        if self._pending:
            if self._pending not in self._pending_capabilities:
                self._pending_capabilities[self._pending] = set(self._active_scope) or set(LABELS)
            self._emergency_previous, self._pending = self._pending, ""
        self._busy = True
        self._active_scope = list(LABELS) if capability == "all" else [capability]
        if save or capability in ("virtual-keyboard", "all", "touch"):
            self.keyboard_test.setVisible(True)
            self.keyboard_test.setFocus()
        self._update_actions()
        self.status.setText("Preparando configuração persistente…" if save else "Preparando habilitação e verificação…")
        self._jobs.run("accessibility-activation-plan", json.dumps({"capability": capability, "save": save}),
                       done=lambda payload: self.activation_planned(capability, save, payload))

    def activation_planned(self, capability, save, payload):
        if self._stopped:
            return
        try:
            plan = ActionPlan.from_dict((payload or {})["plan"])
            if (plan.action != ("accessibility.save-profile" if save else "accessibility.activate")
                    or plan.target.key != capability or plan.target.kind != "entry"):
                raise ValueError("plano de outra capacidade")
        except (KeyError, TypeError, ValueError):
            self._busy = False
            if self._emergency_previous:
                self._pending, self._emergency_previous = self._emergency_previous, ""
            self.status.setText("Não foi possível preparar: " + str((payload or {}).get("reason", "plano ausente/ilegível; nenhuma rotina foi autorizada")))
            self._update_actions()
            return
        self._pending = plan.operation_id
        self._active_scope = sorted(recovery_scope(plan))
        self.status.setText(("Registrando perfil…" if save else "Habilitando e verificando…") + " · código " + self._pending)
        for key in self._active_scope:
            self.cards[key].set_state("busy")
        self._jobs.run("accessibility-save-profile" if save else "accessibility-activate", json.dumps(plan.to_dict()),
                       confirm=True, done=self.completed)

    def save_profile(self):
        if self._busy or self._pending:
            return
        if self._confirm("Registrar configuração para preservar", "Salvar as entradas habilitadas e solicitar ao responsável registrado que preserve as preferências atuais? Estados ausentes ou desconhecidos não serão tratados como saudáveis. Não certifica hardware nem acesso antes do login."):
            self.activate("all", save=True)

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
        self._active_scope = sorted(recovery_scope(ActionPlan.from_dict(plan)))
        self._run("repair", json.dumps(plan), confirm=True)

    def configure(self, command):
        if self._busy:
            return
        messages = {
            'audio-reprobe-enable': ('Recuperar enumeração de áudio',
                'Autorizar a reenumeração do WirePlumber quando o perfil saudável registrado desaparecer '
                'ou as rotas físicas faltarem após falha comprovada por dispositivo ocupado? '
                'O Fôlego verifica a unit, processo, placas, preferência persistida, orçamento e resultado.'),
            'audio-reprobe-disable': ('Pausar reenumeração automática',
                'Desativar a recuperação automática da enumeração de áudio?'),
            "enable": ("Proteger entrada e perfis", "O monitor residente poderá reabilitar entradas registradas e perfis saudáveis conhecidos. "
                       "A reenumeração do áudio segue sua opção própria. "
                       "Desligue esta política antes de desabilitar uma entrada intencionalmente. "
                       "Cada efeito depende do responsável, da identidade e do orçamento verificados."),
            "disable": ("Pausar reparos automáticos", "Desabilitar a recuperação automática de entrada e perfis? A observação pode continuar."),
            "capture": ("Registrar configuração", "Registrar os dispositivos identificados e habilitados como configuração a preservar? "
                        "Leituras incompletas ou recursos ocupados serão recusados. O funcionamento físico ainda precisa de teste."),
            "install": ("Ativar monitor no login", "Criar e iniciar o monitor do Fôlego na sessão do usuário, "
                        "inclusive após fechar a janela? Ele seguirá a política de entrada e não atua na tela de login do sistema."),
            "rearm": ("Rearmar após revisão", "Rearmar o limite de reparos após investigar a causa? "
                      "O estado habilitado e a ausência de operações pendentes serão verificados antes de retomar."),
        }
        if command in messages and self._confirm(*messages[command]):
            self._run(command, "", confirm=True)
        elif command.startswith('audio-reprobe-'):
            self.audio_reprobe_choice.setChecked(bool(self._report and
                self._report.get('policy', {}).get('audio_reprobe_enabled') is True))

    def toggle_automatic(self):
        enabled = self._report and self._report.get("policy", {}).get("enabled") is True
        self.configure("disable" if enabled else "enable")

    def reconcile(self):
        if self._pending and not self._busy:
            self._run("reconcile", self._pending)

    def _select_pending(self):
        selected = self.pending_choice.currentData()
        if selected and not self._busy:
            self._pending = selected
            self.status.setText('Operação pendente ' + selected + ' · verificar antes de repetir')
            self._update_actions()

    def rearm_profile(self, key):
        if self._busy or self._capability_pending(key):
            return
        if self._confirm('Rearmar guarda de ' + NAMES[key].lower(),
                         'Retomar após revisão? O estado saudável, a referência e as operações pendentes serão conferidos.'):
            self._run('profile-rearm', key, confirm=True)

    def _run(self, command, target, *, confirm=False):
        self._busy = True
        self.repair_button.setEnabled(False)
        self.reconcile_button.setEnabled(False)
        self._update_actions()
        settings = command not in ('repair', 'reconcile')
        self._jobs.run("accessibility-" + command, target, confirm=confirm,
                       done=lambda payload: self.completed(payload, settings=settings))

    def completed(self, payload, *, settings=False):
        if self._stopped:
            return
        self._busy = False
        payload = payload or {}
        known = payload.get("outcome") in ("sucesso", "parcial", "recusa", "falha", "cancelamento")
        if settings:
            self.status.setText(str(payload.get('outcome', 'desconhecido')) + ' · ' +
                                str(payload.get('reason', 'Configuração atualizada' if known else 'Consultar configuração atual')))
            self._update_actions()
            self.start()
            return
        wrong_id = bool(self._pending) and payload.get("operation_id") != self._pending
        if not known or wrong_id:
            for key in self._active_scope:
                self.cards[key].set_state("attention")
                self.cards[key].setText("Resultado desconhecido · consultar o código sem repetir")
            self.status.setText("desconhecido · " + str(payload.get("reason", "resposta ausente")) +
                                " · operação " + self._pending + " · não repetir")
            self.reconcile_button.setEnabled(bool(self._pending))
            self.reconcile_button.setVisible(bool(self._pending))
            self._update_actions()
            return
        rows = payload.get("effects", {}).get("capabilities", [])
        if isinstance(rows, list) and len(rows) <= len(LABELS):
            details = []
            for row in rows:
                if (not isinstance(row, dict) or row.get("key") not in self.cards
                        or type(row.get("ready")) is not bool or not isinstance(row.get("reason"), str)):
                    continue
                key = row["key"]
                ready = row["ready"] and row.get("outcome") == "sucesso" and payload.get("operation_id") == self._pending
                context = (payload.get("effects", {}).get("boot_id"), payload.get("effects", {}).get("service_owner"))
                self._verified[key] = {**row, "ready": ready, "context": context}
                self.cards[key].set_state("ready" if ready else "attention")
                self.cards[key].setText("Habilitado no sistema · teste físico pendente" if ready else "Precisa de atenção · detalhes no resultado")
                details.append(NAMES[key] + ": " + row["reason"])
            self.operation_details.setText("\n".join(details))
        if payload.get("operation_id") == self._pending or payload.get("outcome") == "recusa":
            self._pending_capabilities.pop(self._pending, None)
            self._pending = ""
            self.reconcile_button.setVisible(False)
        if self._emergency_previous:
            self._pending, self._emergency_previous = self._emergency_previous, ""
            self.reconcile_button.setVisible(True)
            self.reconcile_button.setEnabled(True)
        self.status.setText(str(payload.get("outcome", "recusa")) + " · " + str(payload.get("reason", "política atualizada")))
        self._update_actions()
        self.start()  # Keep the operation result visible; a poll is not a manual verification.

    def stop(self):
        self._stopped = True
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
