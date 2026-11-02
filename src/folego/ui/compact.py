"""Compact resource/AI monitor with explicit desktop shortcuts.

The widget never takes focus. Resource mutations remain manual in the central
window; the colored tabs request copy, paste, capture or the app-owned keyboard.
Wayland placement is compositor-owned; X11 positions are clamped to live screens.
"""
import os

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from . import title_signal
from .desktop_caps import detect
from .theme import TOKENS, control_icon

POSITION_KEY = "compact/position"
WIDGET_TITLE = "Fôlego — widget"


def clamp_position(x: int, y: int, width: int, height: int,
                   screens: tuple[tuple[int, int, int, int], ...]
                   ) -> tuple[int, int]:
    """Keep the controls on a connected screen, including partial off-screen moves.

    No screens means no proof of geometry: returning the requested origin would
    be a lie. In that case the caller gets (0, 0), which is then clamped by the
    platform; the important part is that hotplug never leaves the window fully
    off-screen.
    """
    if not screens:
        return 0, 0
    for sx, sy, sw, sh in screens:
        overlap_w = min(x + width, sx + sw) - max(x, sx)
        overlap_h = min(y + height, sy + sh) - max(y, sy)
        if overlap_w > 0 and overlap_h > 0:
            return (max(sx, min(x, sx + max(0, sw - width))),
                    max(sy, min(y, sy + max(0, sh - height))))
    sx, sy, sw, sh = screens[0]
    return sx + max(0, (sw - width) // 2), sy + max(0, (sh - height) // 2)


class _QtSettingsStore:
    """Small adapter so tests can use a dict instead of touching user state."""

    def __init__(self):
        from PySide6.QtCore import QSettings
        self._settings = QSettings("folego", "folego")

    def value(self, key, default=None):
        return self._settings.value(key, default)

    def setValue(self, key, value):
        self._settings.setValue(key, value)

    def sync(self):
        self._settings.sync()


class CompactWindow(QWidget):
    def __init__(self, window, *, caps=None, store=None, parent=None):
        super().__init__(parent)
        self._window = window
        self._store = store or _QtSettingsStore()
        self._caps = caps or detect(
            session_type=os.environ.get("XDG_SESSION_TYPE"),
            platform=QGuiApplication.platformName(), tray=False)
        self._drag_offset: QPoint | None = None
        self._force_close = False
        self._paused = False

        # A widget that floats but never steals focus or appears in the taskbar.
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                 Qt.WindowType.WindowDoesNotAcceptFocus)
        if self._caps.keep_above:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle(WIDGET_TITLE)
        self.setAccessibleName("Widget do Fôlego")
        self.setFixedWidth(280)
        self.setStyleSheet(
            "QWidget {font-size:9pt;}"
            f"QFrame#widgetCard {{background:{TOKENS.surface};border:1px solid {TOKENS.border};border-radius:12px;}}"
            f"QLabel {{background:transparent;color:{TOKENS.text};}}"
            f"QLabel#quality {{color:{TOKENS.muted};}}"
            f"QPushButton {{background:{TOKENS.surface_alt};color:{TOKENS.text};border:1px solid {TOKENS.border};"
            "border-radius:7px;padding:2px 4px;}"
            f"QPushButton:hover {{border-color:{TOKENS.accent};}}")
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QStyle
        from .ai_strip import AIStrip
        from .desktop_shortcuts import ShortcutTabs
        from .dashboard_tab import HealthGauge
        self.signal_label = QLabel("Aguardando leitura…")
        self.signal_label.setVisible(False)  # complete title remains in the tooltip
        self.detail_label = QLabel("sem amostra ainda")
        self.detail_label.setWordWrap(True)
        self.detail_label.setObjectName("quality")
        self.detail_label.setStyleSheet(f"color:{TOKENS.text};font-weight:500;")
        self._automation_text = "automação manual · preset equilibrado · nenhum grant ativo"
        self.mode_label = QLabel()
        self.operation_label = QLabel("operação: nenhuma nesta sessão")
        self.caps_label = QLabel(self._caps.note)
        for label in (self.mode_label, self.operation_label, self.caps_label):
            label.setVisible(False)
        self._render_mode()
        self.status_label = QLabel("Aguardando")
        self.status_label.setWordWrap(True)
        self.alert_label = QLabel()
        self.alert_label.setWordWrap(True)
        self.alert_label.setTextFormat(Qt.TextFormat.PlainText)
        self.alert_label.hide()
        self.free_label = QLabel("RAM sem leitura")
        self.free_label.setObjectName("quality")
        self.free_label.setWordWrap(True)
        self.open_button = QPushButton('Central')
        self.open_button.setAccessibleName('Abrir a central do Fôlego')
        self.open_button.setToolTip('Abrir ajustes, prompts e opções do Fôlego')
        self.open_button.clicked.connect(self._open_central)
        from PySide6.QtWidgets import QMenu
        self.control_button = QPushButton()
        self.control_button.setIcon(control_icon(self.style(), 'application-menu', QStyle.StandardPixmap.SP_TitleBarMenuButton))
        self.control_button.setAccessibleName('Controles do widget do Fôlego')
        self.control_button.setToolTip('Controles do Fôlego')
        self.control_menu = QMenu(self.control_button)
        self.hide_action = self.control_menu.addAction('Ocultar widget', self._hide_safely)
        self.quit_action = self.control_menu.addAction('Sair do Fôlego', self._window.quit)
        self.control_button.clicked.connect(lambda: self.control_menu.popup(
            self.control_button.mapToGlobal(self.control_button.rect().bottomLeft())))
        self.pause_button = QPushButton("Pausar")
        self.pause_button.setIcon(control_icon(self.style(), "media-playback-pause", QStyle.StandardPixmap.SP_MediaPause))
        self.pause_button.setAccessibleName("Pausar ou retomar a coleta de telemetria")
        self.pause_button.setToolTip("Pausar monitoramento")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.control_button.setFixedSize(26, 26)
        self.open_button.setMinimumHeight(26)
        for button in (self.open_button, self.control_button, self.pause_button):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.gauge = HealthGauge(compact=True)
        self.gauge.setFixedSize(68, 68)
        gauge_column = QVBoxLayout()
        gauge_column.setSpacing(0)
        gauge_column.addWidget(self.gauge)
        header = QHBoxLayout()
        header.setSpacing(4)
        brand = QLabel("Fôlego")
        brand.setStyleSheet("font-size:10pt;font-weight:600;")
        header.addWidget(brand, 1)
        for button in (self.open_button, self.control_button):
            header.addWidget(button)
        body = QHBoxLayout()
        body.setSpacing(10)
        body.addLayout(gauge_column)
        readings = QVBoxLayout()
        readings.setSpacing(3)
        readings.addWidget(self.status_label)
        readings.addWidget(self.detail_label)
        body.addLayout(readings, 1)
        self.ai_strip = AIStrip(self, monitor=getattr(window, 'ai_monitor', None))
        footer = QHBoxLayout()
        footer.addWidget(self.pause_button)
        footer.addStretch(1)
        footer.addWidget(self.free_label)
        card = QFrame()
        card.setObjectName("widgetCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(10, 6, 10, 6)
        inner.setSpacing(4)
        inner.addLayout(header)
        inner.addLayout(body)
        inner.addWidget(self.alert_label)
        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback_label.hide()
        inner.addWidget(self.feedback_label)
        self.feedback_timer = QTimer(self)
        self.feedback_timer.setSingleShot(True)
        self.feedback_timer.timeout.connect(self._clear_feedback)
        inner.addWidget(self.ai_strip)
        inner.addLayout(footer)
        self._capture_waiting = False
        self._capture_restore = False
        self._keyboard_restore = False
        self.capture_timer = QTimer(self)
        self.capture_timer.setInterval(350)
        self.capture_timer.timeout.connect(self._capture_status)
        self.shortcut_tabs = ShortcutTabs(self, capture_handler=self._print)
        self.shortcut_tabs.customize_requested.connect(self._customize_prompts)
        self.shortcut_tabs.controller.feedback.connect(self._shortcut_result)
        self.shortcut_tabs.controller.payload.connect(self._capture_result)
        self.shortcut_tabs.controller.failed.connect(self._capture_failed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(card)
        layout.addWidget(self.shortcut_tabs)
        app = QGuiApplication.instance()
        app.screenRemoved.connect(self._screen_changed)
        app.screenAdded.connect(self._watch_screen)
        for screen in app.screens():
            self._watch_screen(screen)

    def _shortcut_result(self, message):
        self.feedback_label.setText(message)
        self.feedback_label.show()
        self.feedback_timer.start(7000)
        self.adjustSize()

    def _customize_prompts(self):
        open_editor = getattr(self._window, 'open_custom_prompts', self._window.raise_to_user)
        open_editor()
        self.hide()

    def _print(self):
        from .desktop_preferences import enabled, SHOW_IN_CAPTURE
        controller = self.shortcut_tabs.controller
        if self._capture_waiting or controller.future is not None:
            self._shortcut_result('Aguarde a captura ou solicitação atual')
            return
        try: include = enabled(SHOW_IN_CAPTURE, self._store)
        except ValueError as exc:
            self._shortcut_result(str(exc)); return
        self._capture_waiting = True
        self._capture_restore = not include and self.isVisible()
        self._capture_xy = (self.x(), self.y())
        keyboard = self.shortcut_tabs.keyboard
        self._keyboard_restore = not include and keyboard is not None and keyboard.isVisible()
        if self._keyboard_restore: keyboard.hide()
        if self._capture_restore: self.hide()
        # Let the compositor present the hidden surfaces before Spectacle takes
        # its initial image. The timer remains alive while this widget is hidden.
        QTimer.singleShot(220 if not include else 0, self._launch_capture)

    def _launch_capture(self):
        if not self._capture_waiting: return
        if not self.shortcut_tabs.controller.request('print'):
            self._finish_capture()
            return
        self.capture_timer.start()

    def _capture_status(self):
        controller = self.shortcut_tabs.controller
        if controller.future is None: controller.request('capture-status')

    def _capture_result(self, value):
        if value.get('operation') == 'capture-status' and not value['active']:
            self._finish_capture()

    def _capture_failed(self, _message):
        if self.shortcut_tabs.controller.action == 'print': self._finish_capture()

    def _finish_capture(self):
        self.capture_timer.stop()
        self._capture_waiting = False
        restore, self._capture_restore = self._capture_restore, False
        keyboard, self._keyboard_restore = self._keyboard_restore, False
        if restore and not self._force_close:
            self.show_compact()
            if self._caps.session_type == 'wayland': QTimer.singleShot(80, self._restore_capture_position)
        if keyboard and not self._force_close: QTimer.singleShot(150, self._restore_capture_keyboard)

    def _restore_capture_position(self):
        if self._force_close or not self.isVisible(): return
        if self.shortcut_tabs.controller.future is not None:
            QTimer.singleShot(50, self._restore_capture_position); return
        area = self.screen().availableGeometry()
        x, y = clamp_position(*self._capture_xy, self.width(), self.height(),
                              [(area.x(), area.y(), area.width(), area.height())])
        self.shortcut_tabs.controller.request('capture-place', (x, y, self.width(), self.height()))

    def _restore_capture_keyboard(self):
        if self._force_close or self._capture_waiting: return
        if self.shortcut_tabs.controller.future is not None:
            QTimer.singleShot(50, self._restore_capture_keyboard); return
        keyboard = self.shortcut_tabs.keyboard
        if keyboard is not None: keyboard.show_at(keyboard._position, self.screen())

    def _clear_feedback(self):
        self.feedback_label.hide()
        self.adjustSize()

    # ------------------------------------------------------------------ reading

    def show_snapshot(self, snapshot, *, signal=None):
        signal = signal or title_signal.compute(snapshot)
        self.signal_label.setText(signal.text)
        from .dashboard_tab import headroom_pct
        self.gauge.set_state(headroom_pct(snapshot), signal.level)
        from .dashboard_tab import VERDICT
        verdict, color = VERDICT.get(signal.level, VERDICT["unknown"])
        self.status_label.setText(verdict)
        self.status_label.setStyleSheet(f"color:{color};font-weight:600;")
        memory = "RAM —"
        self.free_label.setText("RAM sem leitura")
        if snapshot.mem is not None and snapshot.mem.mem_total_kb > 0:
            used = 1 - snapshot.mem.mem_available_kb / snapshot.mem.mem_total_kb
            memory = f"RAM {used * 100:.0f}%"
            free = snapshot.mem.mem_available_kb / title_signal.MB
            self.free_label.setText(f"{title_signal.fmt1(free)} GB livres")
        cpu = "CPU —" if snapshot.cpu_busy_frac is None else f"CPU {snapshot.cpu_busy_frac * 100:.0f}%"
        swap = "Swap —"
        if snapshot.swap_total_kb and (not snapshot.sources or snapshot.source("swaps").status == "ok"):
            swap = f"Swap {snapshot.swap_used_kb * 100 // snapshot.swap_total_kb}%"
        measured = [v for v in snapshot.tmpfs if v.quality == "ok" and v.total_bytes]
        temp = f"Temp {max(v.used_frac for v in measured) * 100:.0f}%" if measured else "Temp —"
        self.detail_label.setText(f"{memory}   {cpu}\n{swap}   {temp}")
        alerts = []
        for volume in snapshot.tmpfs:
            if volume.quality != "ok":
                alerts.append(f"{volume.path}: capacidade desconhecida")
            elif volume.is_runtime and (volume.used_frac >= .9 or
                    (volume.inodes_total > 0 and volume.inodes_avail == 0)):
                alerts.append("Runtime crítico — aplicativos podem não abrir")
        degraded = [item.name for item in snapshot.sources if item.status != "ok"]
        if degraded:
            alerts.append("Coleta parcial: " + ", ".join(degraded[:3]))
        if signal.level == "unknown":
            alerts.append("Leitura desconhecida/antiga; aguardando nova observação")
        self.alert_label.setText("\n".join(alerts))
        self.alert_label.setVisible(bool(alerts))
        self._sync_tooltip()
        self.adjustSize()
        self._screen_changed()

    def _sync_tooltip(self):
        self.setToolTip("\n".join(text for text in (
            self.signal_label.text(), self.mode_label.text(), self.operation_label.text(),
            self._caps.note if self._caps.compact_fallback else "") if text))

    def _open_central(self):
        """O botão moderno do widget: volta à UI padrão e recolhe o widget."""
        self._window.raise_to_user()
        self.hide()

    def set_operation(self, text: str):
        """Operation result is separate: it never overwrites the health alert."""
        self.operation_label.setText(f"operação: {text or '—'}")
        self._sync_tooltip()

    def set_automation(self, *, mode: str, preset: str, active_grants: int = 0,
                       error: str = "") -> None:
        """Show the persisted F6 state; this control can neither grant nor run."""
        if error:
            self._automation_text = ("automação em estado ilegível · fail-closed · "
                                     "execução desligada")
        else:
            grants = (f"{active_grants} grant(s) ativo(s)" if active_grants
                      else "nenhum grant ativo")
            self._automation_text = (f"automação {mode} · preset {preset} · "
                                     f"{grants} · execução real desligada")
        self._render_mode()

    def _render_mode(self) -> None:
        state = "PAUSADO" if self._paused else "ativo"
        self.mode_label.setText(f"{self._automation_text} · monitoramento {state}")
        if hasattr(self, "gauge"):
            self._sync_tooltip()

    def set_paused(self, paused: bool):
        self._paused = bool(paused)
        self.pause_button.setText("Retomar" if paused else "Pausar")
        self.pause_button.setToolTip("Retomar monitoramento" if paused else "Pausar monitoramento")
        self.pause_button.setAccessibleDescription("monitoramento pausado" if paused else "monitoramento ativo")
        self._render_mode()

    def _toggle_pause(self):
        toggle = getattr(self._window, "toggle_pause", None)
        if toggle is None:
            return
        paused = toggle()
        if paused is not None:
            self.set_paused(paused)

    # ------------------------------------------------------------------ position

    def _screens(self):
        screens = QGuiApplication.screens()
        return tuple((rect.x(), rect.y(), rect.width(), rect.height())
                     for screen in screens
                     for rect in (screen.availableGeometry(),))

    def _restore_position(self):
        if not self._caps.absolute_position:
            return  # the compositor owns placement of the decorated fallback
        raw = self._store.value(POSITION_KEY, "")
        x = y = None
        try:
            if isinstance(raw, str) and "," in raw:
                x_text, y_text = raw.split(",", 1)
                x, y = int(x_text), int(y_text)
        except (TypeError, ValueError):
            x = y = None
        screens = self._screens()
        if x is None or y is None:
            if screens:
                sx, sy, sw, sh = screens[0]
                x = sx + sw - self.width() - 24
                y = sy + 24
            else:
                x = y = 0
        x, y = clamp_position(x, y, self.width(), self.height(), screens)
        self.move(x, y)

    def _save_position(self):
        if not self._caps.absolute_position:
            return
        point = self.pos()
        self._store.setValue(POSITION_KEY, f"{point.x()},{point.y()}")
        sync = getattr(self._store, "sync", None)
        if sync is not None:
            sync()

    def show_compact(self):
        self._restore_position()
        self.show()
        self.raise_()

    def _watch_screen(self, screen):
        screen.availableGeometryChanged.connect(self._screen_changed)
        self._screen_changed()

    def _screen_changed(self, *_args):
        if self.isVisible() and self._caps.absolute_position:
            x, y = clamp_position(self.x(), self.y(), self.width(), self.height(), self._screens())
            self.move(x, y)

    def _hide_safely(self):
        visible = getattr(self._window, "isVisible", lambda: True)()
        tray = getattr(getattr(self._window, "tray", None), "tray", None)
        if not visible and tray is None:
            self._window.raise_to_user()
        self.hide()

    def force_close(self):
        self.capture_timer.stop()
        self._capture_waiting = False
        self._capture_restore = self._keyboard_restore = False
        self.ai_strip.shutdown()
        self.shortcut_tabs.shutdown()
        self._force_close = True
        self.close()

    # -------------------------------------------------------------------- events

    def mousePressEvent(self, event):
        if not self._caps.absolute_position:
            # Wayland: the compositor moves the window; a press never becomes an act
            handle = self.windowHandle()
            if event.button() == Qt.MouseButton.LeftButton and handle is not None:
                handle.startSystemMove()
                event.accept()
                return
            super().mousePressEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (event.globalPosition().toPoint() -
                                 self.frameGeometry().topLeft())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (
                event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_offset is not None:
            self._drag_offset = None
            self._save_position()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # A double click is not a shortcut for any act.
        event.accept()

    def hideEvent(self, event):
        self._save_position()
        super().hideEvent(event)

    def closeEvent(self, event):
        if self._force_close:
            super().closeEvent(event)
            return
        self._save_position()
        event.ignore()
        self._hide_safely()
