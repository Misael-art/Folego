"""Compact manual desktop controls; workers own all native I/O."""
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot, ClassInfo
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QStyle, QVBoxLayout, QWidget, QMenu

from ..adapters.desktop_tools import DesktopTools
from .theme import TOKENS, control_icon


def _show_desktop_request():
    """Worker-side I/O on the GUI's process-long session bus connection."""
    from PySide6.QtDBus import QDBusConnection, QDBusMessage
    message = QDBusMessage.createMethodCall('org.kde.KWin', '/KWin', 'org.kde.KWin', 'showDesktop')
    message.setArguments([True])
    reply = QDBusConnection.sessionBus().call(message, timeout=2000)
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        raise RuntimeError('Pedido ao desktop não confirmado; não houve repetição')


class DesktopController(QObject):
    result = Signal(str)
    payload = Signal(object)
    failed = Signal(str)
    feedback = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None, *, backend=None):
        super().__init__(parent)
        self.backend = backend or DesktopTools(desktop_show=_show_desktop_request)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="folego-input")
        self.future = None
        self.closed = False
        self.action = ""
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._drain)
        QGuiApplication.instance().aboutToQuit.connect(self.close)
        pool, backend = self.pool, self.backend
        self._disposed = [False]
        disposed = self._disposed
        def dispose():
            if not disposed[0]:
                disposed[0] = True
                try:
                    pool.submit(backend.close)
                except RuntimeError:
                    backend.close()  # interpreter teardown after the executor joined
                pool.shutdown(wait=False, cancel_futures=False)
        self._dispose = dispose
        self.destroyed.connect(dispose)

    def request(self, action, value=None):
        if self.closed or self.future is not None:
            message = 'Aguarde a solicitação atual; nenhuma tecla ficou na fila'
            self.feedback.emit(message)
            self.result.emit(message)
            return False
        self.future = self.pool.submit(self.backend.perform, action, value)
        self.action = action
        self.busy_changed.emit(True)
        self.timer.start()
        return True

    def _drain(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        future, self.future = self.future, None
        try:
            message = future.result()
            if isinstance(message, dict):
                self.payload.emit(message)
                message = message.get('message', '')
            if message and self.action not in ("key", "position"):
                self.feedback.emit(message)
        except Exception as exc:
            # Native diagnostics never include key contents or stderr.
            message = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else "Solicitação não confirmada; confira o desktop"
            self.failed.emit(message)
            self.feedback.emit(message)
        self.busy_changed.emit(False)
        if message:
            self.result.emit(message)

    def close(self):
        if not self.closed:
            self.closed = True
            self.timer.stop()
            # Runs after the sole in-flight task. No UI access from this worker.
            self._dispose()


@ClassInfo(**{"D-Bus Interface": "org.folego.Keyboard"})
class VirtualKeyboard(QWidget):
    """A non-focusing keyboard. Main tab always bottom; separate arrow top."""
    def __init__(self, controller, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self.setWindowTitle("Fôlego — teclado " + uuid.uuid4().hex)
        self.setAccessibleName("Teclado virtual do Fôlego")
        self.controller = controller
        self.shift = False
        self._geometry = None
        self._position = "bottom"
        self.confirmed_geometry = None
        self.observed_geometry = None
        self._placement_event = threading.Event()
        self._ready = os.environ.get('XDG_SESSION_TYPE') != 'wayland'
        self._requested_screen = None
        self._opening = False
        self.setStyleSheet(f"QWidget {{ background:{TOKENS.surface};color:{TOKENS.text};font-size:11pt; }}"
                           f"QPushButton {{ background:{TOKENS.surface_alt};border:1px solid {TOKENS.border};"
                           "border-radius:5px; padding:5px; min-height:26px; }"
                           f"QPushButton:hover {{border-color:{TOKENS.accent};}}")
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.status = QLabel("Teclado · QWERTY · aplicativo em foco")
        self.status.setWordWrap(True)
        header.addWidget(self.status, 1)
        hide = self._button("Fechar", self.hide)
        hide.setIcon(QIcon.fromTheme("window-close"))
        header.addWidget(hide)
        layout.addLayout(header)
        self.letters = []
        for text, codes in (("1234567890", range(2, 12)), ("qwertyuiop", range(16, 26)),
                            ("asdfghjkl", range(30, 39)), ("zxcvbnm", range(44, 51))):
            row = QHBoxLayout()
            row.setSpacing(4)
            for char, code in zip(text, codes):
                button = self._button(char.upper(), lambda checked=False, key=code: self._key(key))
                self.letters.append(button)
                row.addWidget(button)
            layout.addLayout(row)
        row = QHBoxLayout()
        shift = self._button("Shift", self._shift)
        shift.setCheckable(True)
        row.addWidget(shift)
        for text, code, stretch in (("Tab", 15, 0), ("Espaço", 57, 3),
                                     ("Apagar", 14, 0), ("Enter", 28, 0)):
            row.addWidget(self._button(text, lambda checked=False, key=code: self._key(key)), stretch)
        layout.addLayout(row)
        controller.result.connect(self.status.setText)
        controller.result.connect(self._prepared)
        self._pending_position = False
        controller.busy_changed.connect(self._after_busy)
        QGuiApplication.instance().screenRemoved.connect(self._screen_removed)
        from PySide6.QtDBus import QDBusConnection
        self.bus = QDBusConnection.sessionBus()
        self.service = f"org.folego.Keyboard.p{os.getpid()}"
        self.registered = self.bus.registerService(self.service)
        if self.registered:
            self.bus.registerObject("/keyboard", self, QDBusConnection.RegisterOption.ExportAllSlots)

    def _button(self, text, callback):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(callback)
        return button

    def _shift(self):
        self.shift = not self.shift

    def _key(self, code):
        if os.environ.get('XDG_SESSION_TYPE') == 'wayland' and self.confirmed_geometry is None:
            self.status.setText('Aguarde a confirmação de posição e foco do teclado')
            return
        self.controller.request("key", [42, code] if self.shift else [code])

    @Slot(str, str)
    def placed(self, caption, serialized):
        try:
            payload = tuple(json.loads(serialized))
            observed = payload[:4]
        except (ValueError, TypeError):
            return
        self.observed_geometry = observed
        # KWin's fractional logical geometry must match the same physical pixels
        # as Qt's integral coordinates, including a desktop scale such as 135%.
        ratio = self.devicePixelRatioF()
        same_pixels = (len(payload) in (4, 5) and (len(payload) == 4 or payload[4] is True)
                       and len(observed) == 4 and self._geometry is not None
                       and all(round(actual * ratio) == round(wanted * ratio)
                               for actual, wanted in zip(observed, self._geometry)))
        if caption == self.windowTitle() and same_pixels:
            self.confirmed_geometry = self._geometry
            self._placement_event.set()
            self.status.setText("Teclado aberto " + ("no topo" if self._position == "top" else "na parte inferior"))
        else:
            self.observed_geometry = observed
            self.status.setText("Posição não confirmada; confira o teclado")

    def show_at(self, position, screen=None):
        if position not in ("top", "bottom"):
            raise ValueError("posição inválida")
        screen = screen or QGuiApplication.primaryScreen()
        self._position = position
        if not self._ready:
            self._requested_screen = screen
            if not self._opening:
                app = QGuiApplication.instance()
                self._opening = self.controller.request('keyboard-prepare', app.desktopFileName() or app.applicationName())
            return
        self.confirmed_geometry = None
        self._placement_event.clear()
        if screen is None:
            self.status.setText("Tela indisponível")
            return
        area = screen.availableGeometry()
        self.resize(min(960, area.width()), min(max(220, self.sizeHint().height()), area.height()))
        x = area.x() + (area.width() - self.width()) // 2
        y = area.top() if position == "top" else area.bottom() + 1 - self.height()
        self._geometry = (x, y, self.width(), self.height())
        self.move(x, y)
        self.show()
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            self.status.setText("Abrindo teclado na posição solicitada…")
            # Wait only for mapping of our own surface; the worker never blocks Qt.
            self._pending_position = True
            QTimer.singleShot(150, self._position_request)

    def _prepared(self, message):
        if self._opening and self.controller.action == 'keyboard-prepare':
            self._opening = False
            if message.startswith('Teclado preparado'):
                self._ready = True
                # Let KWin consume its reconfigure before mapping this surface.
                QTimer.singleShot(400, lambda: self.show_at(self._position, self._requested_screen))

    def _after_busy(self, busy):
        if not busy and self._pending_position:
            QTimer.singleShot(0, self._position_request)

    def _position_request(self):
        if self._pending_position and self.isVisible() and self.controller.future is None:
            self._pending_position = False
            self.controller.request("position", (self.windowTitle(), self._geometry,
                                                   self.service if self.registered else None,
                                                   self._placement_event))

    def _screen_removed(self, screen):
        if self.isVisible():
            self.show_at(self._position)

    def closeEvent(self, event):
        self.hide()
        event.ignore()


class ShortcutTabs(QWidget):
    customize_requested = Signal()
    def __init__(self, parent=None, *, controller=None):
        super().__init__(parent)
        self.controller = controller or DesktopController(self)
        self.keyboard = None
        self.buttons = {}
        self.prompt_menu = None
        self.custom_menu = None
        self.controller.payload.connect(self._custom_result)
        self.controller.failed.connect(self._custom_failed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 0, 3, 0)
        layout.setSpacing(2)
        editing = QHBoxLayout()
        editing.setSpacing(3)
        for action, text, color in (("select_all", "Selecionar tudo", "#28596b"),
                                    ("delete_all", "Apagar tudo", "#8a4554"),
                                    ("prompts", "Prompts", "#51477d")):
            button = QPushButton(text)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAccessibleName(text if action == 'prompts' else text + " no campo de texto em foco")
            button.setToolTip('Escolher um prompt para copiar' if action == 'prompts' else text + " no campo de texto editável em foco; preserva a área de transferência")
            button.setStyleSheet(f"background:{color};color:white;border:none;border-radius:5px;"
                                 "font-size:8pt;padding:2px;min-height:18px;")
            button.clicked.connect(lambda checked=False, key=action: self.activate(key))
            self.buttons[action] = button
            editing.addWidget(button, 1)
        layout.addLayout(editing)
        tabs = QHBoxLayout()
        tabs.setSpacing(3)
        layout.addLayout(tabs)
        for key, text, color, icon in (("copy", "Copiar", "#2e78a7", "edit-copy"),
                                        ("paste", "Colar", "#287963", "edit-paste"),
                                        ("print", "Print", "#8f651f", "camera-photo"),
                                        ("keyboard", "Teclado", "#7255ab", "input-keyboard")):
            tab = QFrame()
            tab.setStyleSheet(f"QFrame {{background:{color};border-bottom-left-radius:9px;"
                             "border-bottom-right-radius:9px;} QPushButton {background:transparent;"
                             "color:white;border:none;padding:3px 1px;min-height:26px;}"
                             "QPushButton:hover {background:rgba(255,255,255,35);}")
            row = QHBoxLayout(tab)
            row.setContentsMargins(1, 0, 1, 0)
            row.setSpacing(0)
            button = QPushButton(text)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAccessibleName(text)
            button.setToolTip({"copy": "Copiar a seleção do aplicativo em foco",
                               "paste": "Colar no aplicativo em foco",
                               "print": "Selecionar uma região para captura de tela",
                               "keyboard": "Abrir sempre na parte inferior da tela"}[key])
            button.clicked.connect(lambda checked=False, action=key: self.activate(action))
            self.buttons[key] = button
            row.addWidget(button, 1)
            if key == "keyboard":
                self.top_button = QPushButton()
                self.top_button.setIcon(control_icon(self.style(), "go-up", QStyle.StandardPixmap.SP_ArrowUp))
                self.top_button.setFixedWidth(22)
                self.top_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self.top_button.setAccessibleName("Abrir teclado no topo da tela")
                self.top_button.setToolTip("Somente esta seta abre o teclado no topo da tela")
                self.top_button.setStyleSheet("border-left:1px solid #b99ce1;border-radius:4px;")
                self.top_button.clicked.connect(lambda: self.open_keyboard("top"))
                row.addWidget(self.top_button)
            tabs.addWidget(tab, 3 if key == "keyboard" else 2)

    def activate(self, action):
        if action == "keyboard":
            self.open_keyboard("bottom")
        elif action == 'prompts':
            self.show_prompts()
        else:
            self.controller.request(action)

    def show_prompts(self):
        from ..core.development_prompts import PROMPTS
        menu = QMenu(self.buttons['prompts'])
        for prompt in PROMPTS:
            menu.addAction(prompt.title, lambda checked=False, key=prompt.key: self.copy_prompt(key))
        menu.addSeparator()
        self.custom_menu = menu.addMenu('Custom')
        self.custom_menu.addAction('Carregando…').setEnabled(False)
        self.prompt_menu = menu
        menu.aboutToHide.connect(lambda: self._prompts_closed(menu))
        menu.popup(self.buttons['prompts'].mapToGlobal(self.buttons['prompts'].rect().bottomLeft()))
        if not self.controller.request('custom-load'):
            self._custom_failed('Aguarde e reabra o menu Custom')

    def _prompts_closed(self, menu):
        if self.prompt_menu is menu:
            self.prompt_menu = None
            self.custom_menu = None
        menu.deleteLater()

    def _custom_failed(self, message):
        if self.custom_menu is not None and self.controller.action == 'custom-load':
            self.custom_menu.clear()
            self.custom_menu.addAction('Biblioteca indisponível').setEnabled(False)
            self.custom_menu.addAction('Editar textos e macros…', lambda: self.customize_requested.emit())

    def _custom_result(self, payload):
        if payload.get('operation') == 'custom-copy':
            self._copy_text(payload['text'])
        if payload.get('operation') != 'custom-load' or self.custom_menu is None: return
        menu = self.custom_menu
        menu.clear()
        for kind, label in (('text', 'Textos'), ('macro', 'Macros')):
            menu.addSection(label)
            rows = [i for i in payload['entries'] if i['kind'] == kind]
            for item in rows:
                title = item['title']
                shown = menu.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, 300)
                action = menu.addAction(shown)
                action.setToolTip(title)
                value = dict(id=item['id'], revision=payload['revision'])
                action.triggered.connect(lambda checked=False, selected=value: self.controller.request('custom-use', selected))
            if not rows: menu.addAction('Nenhum item cadastrado').setEnabled(False)
        menu.addSeparator()
        menu.addAction('Editar textos e macros…', lambda: self.customize_requested.emit())

    def copy_prompt(self, key):
        from ..core.development_prompts import text
        self._copy_text(text(key))

    def _copy_text(self, value):
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            self.controller.feedback.emit('Área de transferência indisponível')
            return
        clipboard.setText(value)
        self.controller.feedback.emit('Prompt copiado · cole no agente de sua escolha')

    def open_keyboard(self, position):
        if self.keyboard is None:
            self.keyboard = VirtualKeyboard(self.controller)
        self.keyboard.show_at(position, self.screen())

    def shutdown(self):
        if self.keyboard is not None:
            self.keyboard.hide()
            if self.keyboard.registered:
                self.keyboard.bus.unregisterObject("/keyboard")
                self.keyboard.bus.unregisterService(self.keyboard.service)
        self.controller.close()
