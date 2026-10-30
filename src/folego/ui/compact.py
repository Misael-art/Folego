"""Compact control: one glance at the motor, no acts on the system.

It is the floating "widget mode": a small frameless card (mini gauge, one line
of RAM/CPU/swap/temporaries and a button back to the central window) that never
takes focus. On X11 it asks to stay on top and restores its position itself; on
Wayland the compositor owns both, so keep-above and the corner placement come
from an optional KWin window rule (`kwin_rule`), and dragging uses the native
system move.

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
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from . import title_signal
from .desktop_caps import detect
from .theme import TOKENS

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
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle(WIDGET_TITLE)
        self.setAccessibleName("Widget do Fôlego")
        self.setFixedWidth(320)
        self.setStyleSheet(
            f"QFrame#widgetCard {{ background: {TOKENS.surface}; border: 1px solid {TOKENS.border};"
            f" border-radius: 14px; }}"
            f"QLabel {{ background: transparent; color: {TOKENS.text}; }}"
            f"QLabel#headline {{ font-size: 10pt; font-weight: 600; }}"
            f"QLabel#quality {{ color: {TOKENS.muted}; }}"
            f"QPushButton {{ background: {TOKENS.surface_alt}; color: {TOKENS.text};"
            f" border: 1px solid {TOKENS.border}; border-radius: 12px; padding: 3px 8px; }}"
            f"QPushButton#open {{ background: {TOKENS.accent}; color: {TOKENS.accent_text};"
            f" border: none; border-radius: 15px; padding: 6px 14px; font-weight: 600; }}"
            f"QPushButton:hover {{ border-color: {TOKENS.accent}; }}"
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
        # a nota técnica do Wayland vai para o tooltip: o widget mostra só o básico
        self.caps_label.setVisible(False)

        self.open_button = QPushButton("⤢  Abrir Fôlego")
        self.open_button.setObjectName("open")
        self.open_button.setAccessibleName("Voltar à janela central do Fôlego")
        self.open_button.setToolTip("Volta à interface completa e fecha o widget")
        self.open_button.clicked.connect(self._open_central)
        self.hide_button = QPushButton("—")
        self.hide_button.setAccessibleName("Ocultar somente o widget (continua na bandeja)")
        self.hide_button.setToolTip("Ocultar o widget; o Fôlego continua na bandeja")
        self.hide_button.clicked.connect(self._hide_safely)
        self.pause_button = QPushButton("⏸")
        self.pause_button.setAccessibleName(
            "Pausar ou retomar a coleta de telemetria")
        self.pause_button.setToolTip("Pausar monitoramento")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.quit_button = QPushButton("✕")
        self.quit_button.setAccessibleName("Sair do Fôlego e parar o monitoramento")
        self.quit_button.setToolTip("Sair do Fôlego")
        self.quit_button.clicked.connect(self._window.quit)
        for small in (self.hide_button, self.pause_button, self.quit_button):
            small.setFixedSize(30, 26)
        for button in (self.open_button, self.hide_button, self.pause_button, self.quit_button):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # o widget nunca recebe foco

        from .dashboard_tab import HealthGauge
        self.gauge = HealthGauge(compact=True)
        # estado secundário fica no tooltip: o widget mostra só o básico
        for label in (self.mode_label, self.operation_label):
            label.setVisible(False)
        self.signal_label.setMaximumHeight(self.fontMetrics().height() * 3)

        header = QHBoxLayout()
        header.setSpacing(4)
        header.addWidget(self.signal_label, 1)
        for small in (self.pause_button, self.hide_button, self.quit_button):
            header.addWidget(small, 0, Qt.AlignmentFlag.AlignTop)
        body = QHBoxLayout()
        body.addWidget(self.gauge, 0)
        right = QVBoxLayout()
        right.addWidget(self.detail_label)
        right.addStretch(1)
        right.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignRight)
        body.addLayout(right, 1)
        card = QFrame()
        card.setObjectName("widgetCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(12, 10, 12, 12)
        inner.setSpacing(6)
        inner.addLayout(header)
        inner.addLayout(body)
        inner.addWidget(self.mode_label)
        inner.addWidget(self.operation_label)
        inner.addWidget(self.caps_label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(card)
        app = QGuiApplication.instance()
        app.screenRemoved.connect(self._screen_changed)
        app.screenAdded.connect(self._watch_screen)
        for screen in app.screens():
            self._watch_screen(screen)

    # ------------------------------------------------------------------ reading

    def show_snapshot(self, snapshot, *, signal=None):
        signal = signal or title_signal.compute(snapshot)
        self.signal_label.setText(signal.text)
        from .dashboard_tab import headroom_pct
        self.gauge.set_state(headroom_pct(snapshot), signal.level)
        parts = []
        for volume in snapshot.tmpfs:
            if volume.quality != "ok":
                parts.append(f"{volume.path}: capacidade desconhecida")
            elif volume.is_runtime and (volume.used_frac >= .9 or
                    (volume.inodes_total > 0 and volume.inodes_avail == 0)):
                parts.append("Runtime da sessão crítico — aplicativos podem não abrir")
        if snapshot.mem is not None:
            used = 1 - snapshot.mem.mem_available_kb / max(1, snapshot.mem.mem_total_kb)
            free_gb = snapshot.mem.mem_available_kb / title_signal.MB
            parts.append(f"RAM {used * 100:.0f}% (livre {title_signal.fmt1(free_gb)} GB)")
        if snapshot.cpu_busy_frac is None:
            parts.append("CPU ainda sem delta")
        else:
            parts.append(f"CPU {snapshot.cpu_busy_frac * 100:.0f}%")
        if snapshot.swap_total_kb:
            parts.append(f"Swap {snapshot.swap_used_kb * 100 // snapshot.swap_total_kb}%")
        measured = [v for v in snapshot.tmpfs if v.quality == "ok" and v.total_bytes]
        if measured:
            parts.append(f"Temp {max(v.used_frac for v in measured) * 100:.0f}%")
        if snapshot.sources:
            degraded = [item for item in snapshot.sources
                        if item.status in ("partial", "missing", "error")]
            if degraded:
                parts.append("coleta parcial: " +
                             ", ".join(item.name for item in degraded[:3]))
        self.detail_label.setText("\n".join(parts) or "sem detalhes")
        self._sync_tooltip()

    def _sync_tooltip(self):
        self.setToolTip("\n".join(text for text in (
            self.mode_label.text(), self.operation_label.text(),
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
        self.pause_button.setText("▶" if paused else "⏸")
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
