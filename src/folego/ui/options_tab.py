"""Session startup preference; all system/file operations run in a worker."""
import sys
from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import (QCheckBox, QComboBox, QLineEdit, QLabel, QPushButton,
                              QVBoxLayout, QHBoxLayout, QScrollArea, QGroupBox, QLayout, QWidget, QSlider)
from .tune_jobs import TuneJobs
from .theme import TOKENS, THEMES, choose_theme, on_theme_change, choose_transparency, apply_theme, theme_swatch


def options_argv(action, target, confirm):
    if action.startswith("jobs-"):
        argv = [sys.executable, "-m", "folego", "jobs", action.removeprefix("jobs-"), "--json"]
        if action == "jobs-recover": argv.append(target)
        if confirm: argv.append("--confirmar")
        return argv
    argv = [sys.executable, "-m", "folego", "startup", action.removeprefix("startup-"), "--json"]
    if confirm:
        argv.append("--confirmar")
    return argv


class OptionsTab(QWidget):
    operation_verified = Signal(object)
    sound_preview = Signal(str)
    screen_energy_requested = Signal(str)
    power_guard_requested = Signal(str)
    def __init__(self, *, jobs=None):
        super().__init__()
        self._stopped = False
        self._desktop_options = False
        self._screen_energy_state = {'enabled': False, 'message': 'Verificando o Plasma.'}
        self._power_guard_state = {'enabled': False, 'unavailable': True,
                                   'message': 'Verificando o perfil de energia.'}
        self._cooperative_message = 'Pedido cooperativo: aguardando leitura térmica.'
        self._sound_message = 'Sons distintos por agente; alerta em 20%, fim da franquia e reposição confirmada.'
        self.jobs = jobs or TuneJobs(parent=self, argv_factory=options_argv, timeout_ms=30000)
        self.choice = QCheckBox("Iniciar Fôlego automaticamente com a sessão")
        self.choice.setChecked(True)
        self.choice.setAccessibleName("Iniciar automaticamente com a sessão, ligado por padrão")
        self.choice.clicked.connect(self.changed)
        self.status = QLabel("Ligado por padrão; aguardando verificação da configuração efetiva.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.verify = QPushButton("Verificar configuração")
        self.verify.clicked.connect(lambda: self.start())
        self.pending = QComboBox()
        self.pending.setAccessibleName("Operações com resultado pendente")
        self.operation_id = QLineEdit()
        self.operation_id.setPlaceholderText("Cole o código da operação para consultar sem repetir")
        self.operation_id.setAccessibleName("Código da operação a verificar")
        self.operation_id.textChanged.connect(lambda text: self.reconcile.setEnabled(bool(text or self.pending.currentData())))
        self.reconcile = QPushButton("Verificar operação pendente sem repetir")
        self.reconcile.clicked.connect(self.check_operation)
        self.cancel = QPushButton("Cancelar revisão ainda não iniciada")
        self.cancel.clicked.connect(self.cancel_review)
        self.operation_status = QLabel("Nenhuma recuperação solicitada.")
        self.operation_status.setWordWrap(True)
        self.operation_status.setTextFormat(Qt.TextFormat.PlainText)
        self.retention = QLabel("Temporários próprios: ainda não consultados.")
        self.retention.setWordWrap(True)
        self.retention.setTextFormat(Qt.TextFormat.PlainText)
        self.retain = QPushButton("Reter temporários concluídos preservando conteúdo")
        self.retain.clicked.connect(lambda: self.jobs.run("jobs-retain", "", confirm=True, done=self.retained))
        self.retained_runs = QComboBox()
        self.retained_runs.setAccessibleName("Temporário retido a recuperar")
        self.recover_run_button = QPushButton("Localizar conteúdo retido para recuperação")
        self.recover_run_button.setEnabled(False)
        self.recover_run_button.clicked.connect(self.recover_run)
        self.retained_runs.currentIndexChanged.connect(
            lambda: self.recover_run_button.setEnabled(bool(self.retained_runs.currentData())))
        text = QLabel("A opção inicia a central e o monitor com seu login gráfico. "
                      "Não amplia permissões de reparo ou limpeza. Desligar impede o próximo início "
                      "e para a unit própria do monitor de entrada; a central aberta continua na tela.")
        text.setWordWrap(True)
        outer = QVBoxLayout(self)
        area = QScrollArea()
        area.setWidgetResizable(True)
        content = QWidget()
        box = QVBoxLayout(content)
        box.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.settings_box = box
        self.build_theme_options()
        for title, controls in (
            ("Início com a sessão", (self.choice, text, self.status, self.verify)),
            ("Operações pendentes", (self.pending, self.operation_id, self.reconcile, self.cancel,
                                     self.operation_status)),
            ("Temporários do Fôlego", (self.retention, self.retain, self.retained_runs,
                                       self.recover_run_button)),
        ):
            group = QGroupBox(title)
            group_layout = QVBoxLayout(group)
            for widget in controls:
                group_layout.addWidget(widget)
            box.addWidget(group)
        box.addStretch(1)
        area.setWidget(content)
        outer.addWidget(area)

    def build_theme_options(self):
        group = QGroupBox('Aparência · consoles clássicos')
        layout = QVBoxLayout(group)
        self.theme_choice = QComboBox()
        self.theme_choice.setAccessibleName('Tema de cores de todo o Fôlego')
        self.theme_choice.setToolTip('Aplica agora na central, widget, menus, painéis e teclado; mantém a escolha ao reabrir')
        for key, theme in THEMES.items():
            self.theme_choice.addItem(theme_swatch(theme), theme.name, key)
        self.theme_description = QLabel()
        self.theme_description.setWordWrap(True)
        self.theme_status = QLabel()
        self.theme_status.setTextFormat(Qt.TextFormat.PlainText)
        self.theme_status.setWordWrap(True)
        self.background_label = QLabel()
        self.background_slider = QSlider(Qt.Orientation.Horizontal)
        self.background_slider.setRange(0, 100)
        self.background_slider.setSingleStep(1)
        self.background_slider.setPageStep(10)
        self.background_slider.setAccessibleName('Transparência do fundo de todo o Fôlego')
        self.background_slider.setToolTip('0%: fundo opaco · 100%: sem fundo. Textos, ícones e contornos continuam visíveis.')
        self._transparency_origin = TOKENS.transparency
        self.background_slider.sliderPressed.connect(self._transparency_pressed)
        self.background_slider.sliderReleased.connect(self._transparency_released)
        self.background_slider.valueChanged.connect(self._transparency_changed)
        hint = QLabel('Uma escolha para todas as telas. As cores de alerta mantêm o significado: '
                      'verde disponível, âmbar atenção e vermelho crítico, acompanhadas de texto.')
        hint.setWordWrap(True)
        opacity_hint = QLabel('0% opaco · 100% sem fundo. Mantém textos, ícones, teclas e indicadores; ajuste ao fundo da sua tela.')
        opacity_hint.setWordWrap(True)
        for widget in (self.theme_choice, self.theme_description, self.background_label,
                       self.background_slider, opacity_hint, hint, self.theme_status): layout.addWidget(widget)
        self.settings_box.addWidget(group)
        self.sync_theme()
        on_theme_change(self, self.sync_theme)
        self.theme_choice.currentIndexChanged.connect(self.change_theme)

    def sync_theme(self):
        with QSignalBlocker(self.theme_choice):
            self.theme_choice.setCurrentIndex(self.theme_choice.findData(TOKENS.key))
        with QSignalBlocker(self.background_slider):
            self.background_slider.setValue(TOKENS.transparency)
        self.background_label.setText(f'Transparência do fundo · {TOKENS.transparency}%')
        self.theme_description.setText(THEMES[TOKENS.key].description)
        from PySide6.QtWidgets import QApplication
        self.theme_status.setText(QApplication.instance().property('folego_theme_error') or
                                 'Aplicado em todas as telas · escolha salva ao selecionar.')

    def change_theme(self, index):
        if self._stopped: return
        try:
            choose_theme(self.theme_choice.itemData(index))
        except (ValueError, RuntimeError) as exc:
            self.sync_theme()
            self.theme_status.setText(str(exc))

    def _transparency_pressed(self):
        self._transparency_origin = TOKENS.transparency

    def _transparency_changed(self, value):
        if self._stopped: return
        if self.background_slider.isSliderDown():
            # Drag previews contain no configuration I/O. Save once on release.
            apply_theme(theme_id=TOKENS.key, transparency=value)
        else:
            self._transparency_origin = TOKENS.transparency
            self._transparency_released()

    def _transparency_released(self):
        if self._stopped: return
        try:
            choose_transparency(self.background_slider.value())
        except (ValueError, RuntimeError) as exc:
            apply_theme(theme_id=TOKENS.key, transparency=self._transparency_origin)
            self.sync_theme()
            self.theme_status.setText(str(exc))

    def showEvent(self, event):
        super().showEvent(event)
        self.build_desktop_options()

    def build_desktop_options(self):
        if self._desktop_options: return
        from .desktop_preferences import enabled, set_enabled, SHOW_IN_CAPTURE, SOUNDS, RAISE_VOLUME
        self._desktop_options = True
        group = QGroupBox('Captura e avisos sonoros')
        layout = QVBoxLayout(group)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.capture_choice = QCheckBox('Incluir widget flutuante no print')
        self.sound_choice = QCheckBox('Sons de agentes, franquia e bateria')
        self.volume_choice = QCheckBox('Elevar o volume a pelo menos 85% durante o som e restaurar depois')
        self.sound_status = QLabel(self._sound_message)
        self.sound_status.setTextFormat(Qt.TextFormat.PlainText)
        self.sound_status.setWordWrap(True)
        def changed(key, checked):
            try: set_enabled(key, checked)
            except RuntimeError as exc: self.sound_feedback(str(exc))
        for control, key in ((self.capture_choice, SHOW_IN_CAPTURE), (self.sound_choice, SOUNDS), (self.volume_choice, RAISE_VOLUME)):
            try: control.setChecked(enabled(key))
            except ValueError as exc:
                control.setTristate(True); control.setCheckState(Qt.CheckState.PartiallyChecked)
                self.sound_feedback(str(exc))
            control.clicked.connect(lambda checked=False, k=key: changed(k, checked))
            layout.addWidget(control)
        hint = QLabel('Desmarque a opção de print para ocultar o widget ao capturar pelo Fôlego. '
                      'Ele retorna quando você fecha o Spectacle. Alterações de volume feitas por você durante um som são preservadas.')
        hint.setWordWrap(True); layout.addWidget(hint)
        preview = QHBoxLayout()
        self.sound_kind = QComboBox()
        for key, text in (('codex', 'Codex · entrega concluída'), ('web', 'Codex Web · entrega concluída'),
                          ('claude', 'Claude · entrega concluída'), ('grok', 'Grok · entrega concluída'),
                          ('low', 'Atenção · 20% restantes'), ('empty', 'Franquia esgotada'), ('restored', 'Franquia disponível novamente'),
                          ('battery-75', 'Bateria · 75%'), ('battery-50', 'Bateria · 50%'),
                          ('battery-25', 'Bateria · 25%'), ('battery-10', 'Bateria · 10%')):
            self.sound_kind.addItem(text, key)
        self.sound_kind.setAccessibleName('Som para testar')
        self.test_sound = QPushButton('Testar som')
        self.test_sound.clicked.connect(lambda: self.sound_preview.emit(self.sound_kind.currentData()))
        preview.addWidget(self.sound_kind, 1); preview.addWidget(self.test_sound)
        layout.addLayout(preview); layout.addWidget(self.sound_status)
        self.settings_box.insertWidget(1, group)
        screen_group = QGroupBox('Economia da tela · Steam Deck')
        screen_layout = QVBoxLayout(screen_group)
        self.screen_energy_choice = QCheckBox('Apagar a tela interna após inatividade')
        self.screen_energy_choice.setAccessibleName('Economia da tela interna, desligada até ativar')
        self.screen_energy_choice.setEnabled(False)
        self.screen_energy_choice.clicked.connect(
            lambda checked: self.screen_energy_requested.emit('enable' if checked else 'disable'))
        self.screen_energy_status = QLabel('Verificando o Plasma; economia desligada até ativar.')
        self.screen_energy_status.setTextFormat(Qt.TextFormat.PlainText)
        self.screen_energy_status.setWordWrap(True)
        screen_hint = QLabel('Na bateria: 2 minutos. Na tomada sem dock: 3 minutos. '
                             'Movimento, uma entrega confirmada ou alerta térmico reacende a tela. '
                             'Jogo em tela cheia pausa a economia. Com monitor externo ativo, '
                             'o Plasma desloca as janelas e o Fôlego desativa só a tela interna. '
                             'O Plasma pode manter '
                             'a tela acesa quando outro aplicativo inibe a ociosidade.')
        screen_hint.setWordWrap(True)
        screen_layout.addWidget(self.screen_energy_choice)
        screen_layout.addWidget(self.screen_energy_status)
        screen_layout.addWidget(screen_hint)
        self.settings_box.insertWidget(0, screen_group)
        power_group = QGroupBox('Bateria · perfil de energia')
        power_layout = QVBoxLayout(power_group)
        self.power_guard_choice = QCheckBox('Reduzir o perfil de energia quando a voltagem cair')
        self.power_guard_choice.setAccessibleName('Guarda de perfil de energia por voltagem')
        self.power_guard_choice.setEnabled(False)
        self.power_guard_choice.clicked.connect(
            lambda checked: self.power_guard_requested.emit('enable' if checked else 'disable'))
        self.power_guard_status = QLabel('Verificando o perfil de energia.')
        self.power_guard_status.setTextFormat(Qt.TextFormat.PlainText)
        self.power_guard_status.setWordWrap(True)
        power_hint = QLabel('Na descarga: voltagem em atenção pede o perfil equilibrado; crítica pede '
                            'economia. O perfil anterior volta quando o carregador é conectado, se '
                            'você não o tiver trocado. Nenhum aplicativo é fechado.')
        power_hint.setWordWrap(True)
        for widget in (self.power_guard_choice, self.power_guard_status, power_hint):
            power_layout.addWidget(widget)
        self.settings_box.insertWidget(1, power_group)
        self.show_power_guard(self._power_guard_state)
        self.show_screen_energy(self._screen_energy_state)
        self.cooperative_status = QLabel(self._cooperative_message)
        self.cooperative_status.setTextFormat(Qt.TextFormat.PlainText)
        self.cooperative_status.setWordWrap(True)
        screen_layout.addWidget(self.cooperative_status)

    def show_power_guard(self, state):
        self._power_guard_state = state
        if self._stopped or not self._desktop_options: return
        from PySide6.QtCore import QSignalBlocker
        with QSignalBlocker(self.power_guard_choice):
            self.power_guard_choice.setChecked(bool(state.get('enabled')))
        self.power_guard_choice.setEnabled(not state.get('unavailable', False))
        self.power_guard_status.setText(state.get('message', 'Estado do perfil desconhecido'))

    def show_screen_energy(self, state):
        self._screen_energy_state = state
        if self._stopped or not self._desktop_options: return
        from PySide6.QtCore import QSignalBlocker
        with QSignalBlocker(self.screen_energy_choice):
            self.screen_energy_choice.setChecked(bool(state.get('enabled')))
        self.screen_energy_choice.setEnabled(bool(state.get('enabled')) or not state.get('unknown', False))
        self.screen_energy_status.setText(state.get('message', 'Estado da tela desconhecido'))

    def screen_energy_error(self, message):
        self._screen_energy_state = {'enabled': False, 'unknown': True, 'message': message}
        if self._stopped or not self._desktop_options: return
        self.screen_energy_choice.setEnabled(False)
        self.screen_energy_status.setText(message)

    def show_cooperative_state(self, state):
        self._cooperative_message = state.get('message', 'Pedido cooperativo sem confirmação')
        if self._desktop_options: self.cooperative_status.setText(self._cooperative_message)

    def cooperative_error(self, message):
        self._cooperative_message = 'Pedido cooperativo indisponível: ' + message
        if self._desktop_options: self.cooperative_status.setText(self._cooperative_message)

    def sound_feedback(self, message):
        if self._stopped: return
        self._sound_message = message
        if self._desktop_options: self.sound_status.setText(message)

    def start(self, *, sync=False):
        if self._stopped: return
        self.choice.setEnabled(False)
        self.jobs.run("startup-sync" if sync else "startup-status", "", done=self.done)
        self.jobs.run("review-pending", "", done=self.show_pending)
        self.jobs.run("jobs-status", "", done=self.show_retention)

    def show_pending(self, payload):
        if self._stopped: return
        self.pending.clear()
        rows = (payload or {}).get("pending")
        if not isinstance(rows, list):
            self.pending.addItem("Consulta de operações indisponível", None)
            self.reconcile.setEnabled(False)
            self.cancel.setEnabled(False)
            return
        for row in rows:
            self.pending.addItem(row["action"] + " · " + row["operation_id"], row["operation_id"])
        self.reconcile.setEnabled(bool(rows or self.operation_id.text().strip()))
        self.cancel.setEnabled(bool(rows))
        if not rows:
            self.pending.addItem("Nenhuma revisão/operação pendente", None)

    def check_operation(self):
        key = self.operation_id.text().strip() or self.pending.currentData()
        if key:
            self.jobs.run("review-reconcile", key, done=lambda result: self.operation_result(key, result))

    def cancel_review(self):
        key = self.pending.currentData()
        if key:
            self.jobs.run("review-cancel", key, confirm=True, done=lambda result: self.operation_result(key, result))

    def operation_result(self, key, payload):
        if not payload or payload.get("operation_id") != key:
            payload = {"outcome": "desconhecido", "operation_id": key,
                       "reason": "resposta ausente ou de outro código; não repetir a operação"}
        self.retained(payload)

    def show_retention(self, payload):
        if self._stopped: return
        value = payload or {}
        self.retained_runs.clear()
        for row in value.get("retained_runs", []):
            self.retained_runs.addItem(row["name"] + " · " + row["state"],
                                      row["name"] if row["state"] == "complete" else None)
        self.recover_run_button.setEnabled(bool(self.retained_runs.currentData()))
        if "runs" in value:
            self.retention.setText(f"Temporários próprios: {value['runs']}/{value['limit']} ativos · "
                                   f"{value.get('retained_count', 0)} retidos · " + str(value.get("archive", "")))
        else:
            self.retention.setText("Retenção desconhecida: " + str(value.get("reason", "resposta ausente")))

    def recover_run(self):
        run_id = self.retained_runs.currentData()
        if run_id:
            self.jobs.run("jobs-recover", run_id, done=self.retained)

    def retained(self, payload):
        if self._stopped: return
        self.operation_status.setText(str((payload or {}).get("outcome", "")) + " · " +
                                     str((payload or {}).get("path") or
                                         (payload or {}).get("reason", "resultado desconhecido; verificar novamente")))
        if (payload or {}).get("operation_id"):
            if payload.get("outcome") in ("sucesso", "recusa", "cancelamento"):
                self.operation_verified.emit(payload)
            self.jobs.run("review-pending", "", done=self.show_pending)
        if "archived" in (payload or {}):
            self.jobs.run("jobs-status", "", done=self.show_retention)

    def changed(self, checked):
        if self._stopped: return
        self.choice.setEnabled(False)
        self.jobs.run("startup-enable" if checked else "startup-disable", "", confirm=True, done=self.done)

    def done(self, payload):
        if self._stopped: return
        self.choice.setEnabled(True)
        if type((payload or {}).get("enabled")) is bool:
            self.choice.setTristate(False)
            self.choice.setChecked(payload["enabled"])
        else:
            self.choice.setTristate(True)
            self.choice.setCheckState(Qt.CheckState.PartiallyChecked)
            self.choice.setEnabled(False)
        if payload and "effective" in payload:
            self.status.setText("Preferência: " + ("ligada" if payload["enabled"] else "desligada") +
                                " · autostart: " + ("configurado" if payload["configured"] else "ainda não configurado") +
                                " · monitor: " + str(payload.get("service", {}).get("state", "desconhecido")) +
                                " · monitor no login: " + ("ligado" if payload.get("service", {}).get("enabled") else "não comprovado/desligado") +
                                (" · " + payload["reason"] if payload.get("reason") else ""))
        else:
            self.status.setText(str((payload or {}).get("outcome", "desconhecido")) + " · " +
                                str((payload or {}).get("reason", "resposta não comprovada; verificar novamente")))

    def stop(self):
        self._stopped = True
        self.jobs.shutdown()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)
