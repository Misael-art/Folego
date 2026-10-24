"""Compact control: one glance at the motor, no acts on the system.

The compact window is the fallback when a Wayland compositor cannot prove
absolute placement or keep-above. It shows the same signal as the title, keeps
the last completed operation in a separate line (a success never erases a
persistent alert), and offers only navigation, pause and quit. There is no
quick mutation: automation is still disabled until F6 grants exist.

Dragging moves the window and nothing else; buttons are the only controls that
do anything, so a drag cannot become a click. The saved position is clamped to a
currently connected screen before every show, which handles monitor hotplug.
"""
import os

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QGridLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from . import title_signal
from .desktop_caps import detect
from .theme import TOKENS

POSITION_KEY = "compact/position"


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

        flags = Qt.WindowType.Window if self._caps.compact_fallback else (
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        if self._caps.keep_above:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setWindowTitle("Fôlego — controle compacto")
        self.setAccessibleName("Controle compacto do Fôlego")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.resize(420, 380)
        self.setStyleSheet(
            f"QWidget {{ background: {TOKENS.surface}; color: {TOKENS.text}; }}"
            f"QLabel#headline {{ font-size: 13pt; font-weight: 600; }}"
            f"QLabel#quality {{ color: {TOKENS.muted}; }}"
            f"QPushButton {{ background: {TOKENS.surface_alt}; color: {TOKENS.text};"
            f" border: 1px solid {TOKENS.border}; border-radius: 6px;"
            f" padding: 4px 8px; }}"
            f"QPushButton:focus {{ border: 2px solid {TOKENS.focus}; }}")

        self.signal_label = QLabel("Aguardando leitura…")
        self.signal_label.setObjectName("headline")
        self.signal_label.setWordWrap(True)
        self.signal_label.setAccessibleName("Saúde atual")
        self.detail_label = QLabel("sem amostra ainda")
        self.detail_label.setObjectName("quality")
        self.detail_label.setWordWrap(True)
        self._automation_text = ("automação manual · preset equilibrado · "
                                 "nenhum grant ativo")
        self.mode_label = QLabel()
        self.mode_label.setObjectName("quality")
        self.mode_label.setWordWrap(True)
        self._render_mode()
        self.operation_label = QLabel("operação: nenhuma nesta sessão")
        self.operation_label.setObjectName("quality")
        self.operation_label.setWordWrap(True)
        self.caps_label = QLabel(self._caps.note)
        self.caps_label.setObjectName("quality")
        self.caps_label.setWordWrap(True)
        self.caps_label.setVisible(bool(self._caps.compact_fallback))

        self.open_button = QPushButton("Abrir central")
        self.open_button.setAccessibleName("Abrir a janela central do Fôlego")
        self.open_button.clicked.connect(self._window.raise_to_user)
        self.hide_button = QPushButton("Ocultar controle")
        self.hide_button.setAccessibleName("Ocultar somente o controle compacto")
        self.hide_button.clicked.connect(self._hide_safely)
        self.pause_button = QPushButton("Pausar monitoramento")
        self.pause_button.setAccessibleName(
            "Pausar ou retomar a coleta de telemetria")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.quit_button = QPushButton("Sair do Fôlego")
        self.quit_button.setAccessibleName("Sair do Fôlego e parar o monitoramento")
        self.quit_button.clicked.connect(self._window.quit)

        buttons = QGridLayout()
        for index, button in enumerate((self.open_button, self.hide_button, self.pause_button,
                                        self.quit_button)):
            buttons.addWidget(button, index // 2, index % 2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)
        layout.addWidget(self.signal_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.mode_label)
        layout.addWidget(self.operation_label)
        layout.addWidget(self.caps_label)
        layout.addLayout(buttons)
        app = QGuiApplication.instance()
        app.screenRemoved.connect(self._screen_changed)
        app.screenAdded.connect(self._watch_screen)
        for screen in app.screens():
            self._watch_screen(screen)

    # ------------------------------------------------------------------ reading

    def show_snapshot(self, snapshot, *, signal=None):
        signal = signal or title_signal.compute(snapshot)
        self.signal_label.setText(signal.text)
        parts = []
        for volume in snapshot.tmpfs:
            if volume.quality != "ok":
                parts.append(f"{volume.path}: capacidade desconhecida")
            elif volume.is_runtime and (volume.used_frac >= .9 or
                    (volume.inodes_total > 0 and volume.inodes_avail == 0)):
                parts.append("Runtime da sessão crítico — aplicativos podem não abrir")
        if snapshot.mem is not None:
            free_gb = snapshot.mem.mem_available_kb / title_signal.MB
            parts.append(f"livre {title_signal.fmt1(free_gb)} GB")
        if snapshot.cpu_busy_frac is None:
            parts.append("cpu ainda sem delta")
        else:
            parts.append(f"cpu {snapshot.cpu_busy_frac * 100:.0f}%")
        if snapshot.sources:
            degraded = [item for item in snapshot.sources
                        if item.status in ("partial", "missing", "error")]
            if degraded:
                parts.append("coleta parcial: " +
                             ", ".join(item.name for item in degraded[:3]))
        self.detail_label.setText(" · ".join(parts) or "sem detalhes")

    def set_operation(self, text: str):
        """Operation result is separate: it never overwrites the health alert."""
        self.operation_label.setText(f"operação: {text or '—'}")

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

    def set_paused(self, paused: bool):
        self._paused = bool(paused)
        self.pause_button.setText("Retomar monitoramento" if paused
                                  else "Pausar monitoramento")
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
        self._force_close = True
        self.close()

    # -------------------------------------------------------------------- events

    def mousePressEvent(self, event):
        if not self._caps.absolute_position:
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
