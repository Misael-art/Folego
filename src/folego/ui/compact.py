"""Compact resource/AI monitor with explicit desktop shortcuts.

The widget never takes focus. Resource mutations remain manual in the central
window; the colored tabs request copy, paste, capture or the app-owned keyboard.
Wayland placement is compositor-owned; X11 positions are clamped to live screens.
"""
import math
import os

from PySide6.QtCore import (QPoint, QRect, QRectF, Qt, QTimer, QPropertyAnimation,
                            QVariantAnimation, QEasingCurve, QEvent)
from PySide6.QtGui import (QActionGroup, QGuiApplication, QWindow, QFont, QPainter,
                           QPainterPath, QPen, QColor, QRegion)
from PySide6.QtWidgets import (QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget, QSizePolicy, QApplication,
                               QGraphicsOpacityEffect)

from . import title_signal
from .desktop_caps import detect
from .theme import (_background_color, background, themed_style, TOKENS, THEMES, choose_theme,
                    set_control_icon, on_theme_change, theme_swatch)
from .palettes import readable
from .mini_ai_strip import MiniAIStrip
from ..core.battery_alerts import (VOLTAGE_BANDS, VOLTAGE_NAMES, battery_band, remaining_text,
                                    voltage_level, voltage_sag, voltage_text)

POSITION_KEY = "compact/position"
WIDGET_TITLE = "Fôlego — widget"
FLOAT_MODES = ('compact', 'mini')
DOCK_MODES = (*FLOAT_MODES, 'right', 'left', 'top')
MINI_WIDTH = 384
MINI_HEIGHT = 46
COMPACT_WIDTH = 268
SLIM_TOP_WIDTH = 900
SLIM_TOP_HEIGHT = 120


def dock_geometry(mode: str, area: QRect) -> QRect:
    """Use only the screen's available area, which excludes known desktop panels."""
    if mode not in ('right', 'left', 'top') or not area.isValid():
        raise ValueError('Borda ou tela indisponível')
    if mode == 'top':
        height = min(area.height(), SLIM_TOP_HEIGHT if area.width() >= SLIM_TOP_WIDTH else 190)
        return QRect(area.left(), area.top(), area.width(), height)
    width = min(128, max(112, area.width() // 12))
    width = min(width, area.width())
    x = area.left() if mode == 'left' else area.right() + 1 - width
    return QRect(x, area.top(), width, area.height())


class DockHandle(QPushButton):
    """A subtle edge target that reveals two darker tones and an arrow on hover."""
    def __init__(self, arrow, title, callback, parent):
        super().__init__(parent)
        self.arrow = arrow
        self.hovered = False
        self.setAccessibleName(title)
        self.setToolTip(title)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet('QPushButton{background:transparent;border:none;padding:0;min-height:0;min-width:0;}')
        self.clicked.connect(callback)

    def enterEvent(self, event):
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        if not self.hovered:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TOKENS.surface).darker(130))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setBrush(QColor(TOKENS.surface).darker(160))
        if self.arrow in ('left', 'right'):
            x = rect.left() if self.arrow == 'right' else rect.right() - 4
            painter.drawRect(QRectF(x, rect.top() + 5, 4, rect.height() - 10))
        else:
            y = rect.top() if self.arrow == 'down' else rect.bottom() - 4
            painter.drawRect(QRectF(rect.left() + 5, y, rect.width() - 10, 4))
        painter.setPen(QPen(QColor(TOKENS.text), 2.2, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cx, cy = rect.center().x(), rect.center().y()
        if self.arrow == 'right':
            painter.drawLine(QPoint(int(cx - 4), int(cy - 5)), QPoint(int(cx + 2), int(cy)))
            painter.drawLine(QPoint(int(cx + 2), int(cy)), QPoint(int(cx - 4), int(cy + 5)))
        elif self.arrow == 'left':
            painter.drawLine(QPoint(int(cx + 4), int(cy - 5)), QPoint(int(cx - 2), int(cy)))
            painter.drawLine(QPoint(int(cx - 2), int(cy)), QPoint(int(cx + 4), int(cy + 5)))
        elif self.arrow == 'up':
            painter.drawLine(QPoint(int(cx - 5), int(cy + 3)), QPoint(int(cx), int(cy - 3)))
            painter.drawLine(QPoint(int(cx), int(cy - 3)), QPoint(int(cx + 5), int(cy + 3)))
        else:
            painter.drawLine(QPoint(int(cx - 5), int(cy - 3)), QPoint(int(cx), int(cy + 3)))
            painter.drawLine(QPoint(int(cx), int(cy + 3)), QPoint(int(cx + 5), int(cy - 3)))
        painter.end()


class MiniDragHandle(QWidget):
    """A visible grip; only this region starts a compositor move."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        on_theme_change(self, self.update)
        self.setFixedSize(16, 32)
        self.setAccessibleName('Arrastar a faixa mínima')
        self.setToolTip('Arraste para mover a faixa')
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._offset = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TOKENS.muted))
        for x in (5, 11):
            for y in (10, 16, 22):
                painter.drawEllipse(QPoint(x, y), 1, 1)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if self.owner._caps.absolute_position:
            self._offset = event.globalPosition().toPoint() - self.owner.frameGeometry().topLeft()
        else:
            surface = self.owner.windowHandle()
            if surface is not None:
                surface.startSystemMove()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.owner.move(event.globalPosition().toPoint() - self._offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._offset is not None:
            self._offset = None
            self.owner._save_position()
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()


class RoundedCard(QFrame):
    """Paint the surface within the radius, including translucent themes."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 12, 12)
        painter.fillPath(path, _background_color(TOKENS.surface))
        painter.setPen(QPen(QColor(TOKENS.border), 1))
        painter.drawPath(path)
        painter.end()


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
        self.setFixedWidth(COMPACT_WIDTH)
        themed_style(self, lambda: "QWidget {font-size:9pt;}"
            "QFrame#widgetCard {background:transparent;border:none;}"
            f"QLabel {{background:transparent;color:{TOKENS.text};}}"
            f"QLabel#quality {{color:{TOKENS.muted};}}"
            f"QPushButton {{background:{background(TOKENS.surface_alt)};color:{TOKENS.text};border:1px solid {TOKENS.border};"
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
        themed_style(self.detail_label, lambda: f"color:{TOKENS.text};font-weight:500;")
        self.battery_label = QLabel()
        self.battery_label.hide()
        self._battery_band = 'green'
        self._voltage_band = None
        self._voltage_text = ''
        self._battery_text = ''
        themed_style(self.battery_label, self._battery_style)
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
        self.open_button = QPushButton()
        set_control_icon(self.open_button, 'view-grid', QStyle.StandardPixmap.SP_FileDialogContentsView)
        self.open_button.setAccessibleName('Abrir a central do Fôlego')
        self.open_button.setToolTip('Abrir ajustes, prompts e opções do Fôlego')
        self.open_button.clicked.connect(self._open_central)
        from PySide6.QtWidgets import QMenu
        self.control_button = QPushButton()
        set_control_icon(self.control_button, 'go-down', QStyle.StandardPixmap.SP_ArrowDown)
        self.control_button.setAccessibleName('Controles do widget do Fôlego')
        self.control_button.setToolTip('Mudar visualização e outros controles')
        self.control_menu = QMenu(self.control_button)
        self.control_button.clicked.connect(lambda: self.control_menu.popup(
            self.control_button.mapToGlobal(self.control_button.rect().bottomLeft())))
        self.pause_button = QPushButton("Pausar")
        set_control_icon(self.pause_button, "media-playback-pause", QStyle.StandardPixmap.SP_MediaPause)
        self.pause_button.setAccessibleName("Pausar ou retomar a coleta de telemetria")
        self.pause_button.setToolTip("Pausar monitoramento")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.control_button.setFixedSize(20, 28)
        self.open_button.setFixedSize(30, 28)
        for button in (self.open_button, self.control_button, self.pause_button):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.gauge = HealthGauge(compact=True)
        self.gauge.setFixedSize(68, 68)
        gauge_column = QVBoxLayout()
        gauge_column.setSpacing(0)
        gauge_column.addWidget(self.gauge)
        self.header_widget = QWidget()
        header = QGridLayout(self.header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        self.header_layout = header
        self.brand = QLabel("FÔLEGO")
        font = QFont('Noto Sans', 11)
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.2)
        self.brand.setFont(font)
        header.addWidget(self.brand, 0, 0)
        header.setColumnStretch(0, 1)
        self.body_widget = QWidget()
        self.body_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.body_widget)
        body = self.body_layout
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        gauge_widget = QWidget()
        gauge_widget.setLayout(gauge_column)
        self._gauge_margins = gauge_column.contentsMargins()
        body.addWidget(gauge_widget)
        self.gauge_widget = gauge_widget
        readings = QVBoxLayout()
        self.readings_layout = readings
        readings.setSpacing(3)
        self.summary_row = QHBoxLayout()
        self.summary_row.setSpacing(4)
        self.summary_row.addWidget(self.status_label, 1)
        readings.addLayout(self.summary_row)
        readings.addWidget(self.detail_label)
        readings.addWidget(self.battery_label)
        readings_widget = QWidget()
        readings_widget.setLayout(readings)
        self._readings_margins = readings.contentsMargins()
        body.addWidget(readings_widget, 1)
        self.readings_widget = readings_widget
        self.ai_strip = AIStrip(self, monitor=getattr(window, 'ai_monitor', None))
        self.footer_widget = QWidget()
        footer = QHBoxLayout(self.footer_widget)
        self.footer_layout = footer
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(self.pause_button)
        footer.addStretch(1)
        footer.addWidget(self.free_label)
        self.card = RoundedCard()
        self.card.setObjectName("widgetCard")
        on_theme_change(self.card, self.card.update)
        self.inner = QGridLayout(self.card)
        self.inner.setContentsMargins(10, 6, 10, 6)
        self.inner.setSpacing(4)
        self.notice_widget = QWidget()
        notices = QVBoxLayout(self.notice_widget)
        self.notices_layout = notices
        notices.setContentsMargins(0, 0, 0, 0)
        notices.setSpacing(2)
        notices.addWidget(self.alert_label)
        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback_label.hide()
        notices.addWidget(self.feedback_label)
        self.feedback_timer = QTimer(self)
        self.feedback_timer.setSingleShot(True)
        self.feedback_timer.timeout.connect(self._clear_feedback)
        self._sections = (self.header_widget, self.body_widget, self.notice_widget,
                          self.ai_strip, self.footer_widget)
        self._dock_mode = 'compact'
        self._dock_pending = None
        self._dock_target = None
        self._needs_show_reconcile = False
        self._requested_mode = None
        self._needs_compact_clamp = False
        self._show_clamp_phase = None
        self._dock_verify_phase = None
        self._dock_verify_attempts = 0
        self._dock_verify_waits = 0
        self._compact_geometry = None
        self._mini_geometry = None
        self._mini_latest = None
        self._capture_waiting = False
        self._capture_restore = False
        self._keyboard_restore = False
        self.capture_timer = QTimer(self)
        self.capture_timer.setInterval(350)
        self.capture_timer.timeout.connect(self._capture_status)
        self.shortcut_tabs = ShortcutTabs(self, capture_handler=self._print)
        keyboard_button = self.shortcut_tabs.buttons['keyboard']
        keyboard_button.setFixedSize(30, 28)
        self.shortcut_tabs.top_button.setFixedSize(20, 28)
        for name, controls in (('keyboardGroup', (keyboard_button, self.shortcut_tabs.top_button)),
                               ('navigationGroup', (self.open_button, self.control_button))):
            group = QFrame(self)
            group.setObjectName(name)
            row = QHBoxLayout(group)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            for control in controls:
                themed_style(control, lambda: f'QPushButton{{background:transparent;color:{TOKENS.text};'
                             'border:none;border-radius:0;padding:0;min-height:0;}'
                             f'QPushButton:hover{{background:{background(TOKENS.surface_alt)};}}')
                row.addWidget(control)
            themed_style(group, lambda target=name: f'QFrame#{target}{{background:transparent;'
                         f'border:1px solid {TOKENS.border};border-radius:7px;}}')
            if name == 'keyboardGroup':
                self.keyboard_group = group
                header.addWidget(group, 0, 1)
            else:
                self.navigation_group = group
                header.addWidget(group, 0, 2)
        self.top_controls = QWidget(self.card)
        self.top_controls_layout = QGridLayout(self.top_controls)
        self.top_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.top_controls_layout.setSpacing(2)
        self.mini_bar = QWidget(self.card)
        self.mini_bar.setAccessibleName('Faixa mínima do Fôlego')
        self.mini_layout = QHBoxLayout(self.mini_bar)
        self.mini_layout.setContentsMargins(2, 0, 2, 0)
        self.mini_layout.setSpacing(6)
        self.mini_drag = MiniDragHandle(self)
        self.mini_status = QLabel('● Aguardando')
        self.mini_cpu = QLabel('—')
        self.mini_temperature = QLabel('— °C')
        self.mini_memory = QLabel('—')
        self.mini_battery = QLabel('—')
        for label in (self.mini_status, self.mini_cpu, self.mini_temperature,
                      self.mini_memory, self.mini_battery):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.mini_voltage = QLabel('')
        self.mini_voltage.setTextFormat(Qt.TextFormat.PlainText)
        self.mini_voltage.setAccessibleName('Voltagem da bateria')
        self.mini_voltage.hide()
        status_font = QFont(self.mini_status.font())
        status_font.setPointSize(9)
        self.mini_status.setFont(status_font)
        self.mini_layout.addWidget(self.mini_drag)
        self.mini_layout.addWidget(self.mini_status)
        for caption, label, name in (('CPU', self.mini_cpu, 'Uso da CPU'),
                                     ('TEMP', self.mini_temperature, 'Temperatura'),
                                     ('RAM', self.mini_memory, 'RAM em uso'),
                                     ('BAT', self.mini_battery, 'Bateria')):
            cell = QFrame()
            cell.setObjectName('miniMetric')
            cell.setFixedHeight(34)
            themed_style(cell, lambda: f'QFrame#miniMetric{{background:{background(TOKENS.surface_alt)};'
                         'border:0;border-radius:6px;}')
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(6, 2, 6, 2)
            cell_layout.setSpacing(0)
            title = QLabel(caption)
            themed_style(title, lambda: f'background:transparent;color:{TOKENS.muted};font-size:7pt;')
            label.setAccessibleName(name)
            self._set_mini_metric(label, label.text(), 'muted')
            cell_layout.addWidget(title)
            if label is self.mini_battery:
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(4)
                row.addWidget(label)
                row.addWidget(self.mini_voltage)
                cell_layout.addLayout(row)
            else:
                cell_layout.addWidget(label)
            self.mini_layout.addWidget(cell)
            if label is self.mini_temperature:
                self.mini_temperature_caption = title
            elif label is self.mini_battery:
                self.mini_battery_cell = cell
                cell.hide()
        self.mini_ai = MiniAIStrip(self.ai_strip.monitor, self.mini_bar)
        self.mini_ai.details_requested.connect(self._mini_account_details)
        self.mini_layout.addWidget(self.mini_ai)
        self.mini_fit_timer = QTimer(self)
        self.mini_fit_timer.setSingleShot(True)
        self.mini_fit_timer.timeout.connect(self._fit_mini)
        self.mini_ai.changed.connect(self._schedule_mini_fit)
        self.mini_expand = QPushButton()
        set_control_icon(self.mini_expand, 'view-restore', QStyle.StandardPixmap.SP_TitleBarNormalButton)
        self.mini_expand.setFixedSize(32, 32)
        self.mini_expand.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mini_expand.setAccessibleName('Expandir para o widget compacto')
        self.mini_expand.setToolTip('Expandir para o widget compacto')
        self.mini_expand.clicked.connect(lambda: self.set_dock_mode('compact'))
        self.mini_layout.addStretch(1)
        self.mini_layout.addWidget(self.mini_expand)
        self.mini_bar.hide()
        self.layout_menu = QMenu('Visualizações', self.control_button)
        self.layout_actions = {}
        self.layout_action_group = QActionGroup(self)
        self.layout_action_group.setExclusive(True)
        for label, mode in (('Mini horizontal', 'mini'), ('Widget compacto', 'compact'),
                            ('Lateral esquerda', 'left'), ('Lateral direita', 'right'),
                            ('Barra superior', 'top')):
            action = self.layout_menu.addAction(
                label, lambda checked=False, target=mode: self.set_dock_mode(target))
            action.setCheckable(True)
            self.layout_action_group.addAction(action)
            self.layout_actions[mode] = action
        # Put destinations directly in the main menu: one selection from every form.
        self.control_menu.addActions(self.layout_menu.actions())
        self.control_menu.addAction('Abrir Central', self._open_central)
        self.control_menu.addSeparator()
        self.accounts_menu = self.control_menu.addMenu('Contas e cotas de IA')
        self.accounts_menu.aboutToShow.connect(self._refresh_accounts_menu)
        self.theme_menu = self.control_menu.addMenu('Tema de cores')
        self.theme_actions = QActionGroup(self.theme_menu)
        self.theme_actions.setExclusive(True)
        for key, theme in THEMES.items():
            action = self.theme_menu.addAction(theme_swatch(theme), theme.name)
            action.setCheckable(True)
            action.setData(key)
            self.theme_actions.addAction(action)
        self.theme_actions.triggered.connect(self._change_theme)
        self._sync_theme_menu()
        on_theme_change(self, self._theme_changed)
        self.monitoring_menu = self.control_menu.addMenu('Monitoramento')
        self.pause_action = self.monitoring_menu.addAction('Pausar monitoramento', self._toggle_pause)
        self.hide_action = self.control_menu.addAction('Ocultar widget', self._hide_safely)
        self.quit_action = self.control_menu.addAction('Sair do Fôlego', self._window.quit)
        self.control_menu.aboutToShow.connect(self._sync_layout_actions)
        self._sync_layout_actions()
        self.shortcut_tabs.customize_requested.connect(self._customize_prompts)
        self.shortcut_tabs.controller.feedback.connect(self._shortcut_result)
        self.shortcut_tabs.controller.payload.connect(self._capture_result)
        self.shortcut_tabs.controller.failed.connect(self._capture_failed)
        self.shortcut_tabs.controller.busy_changed.connect(
            lambda busy: self._screen_changed() if not busy and self._dock_mode not in FLOAT_MODES else None)
        self.shortcut_tabs.controller.busy_changed.connect(
            lambda busy: self._reconcile_after_show() if not busy else None)
        self.shortcut_tabs.controller.busy_changed.connect(
            lambda busy: self._reconcile_compact_after_show() if not busy else None)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.card)
        self.dock_scroll = QScrollArea(self)
        self.dock_scroll.setWidgetResizable(True)
        self.dock_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.dock_scroll.setStyleSheet('QScrollArea {background:transparent;border:0;}')
        self.dock_scroll.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.dock_scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.dock_scroll.viewport().setAutoFillBackground(False)
        self.card.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.dock_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.dock_scroll.hide()
        self.side_content = QWidget(self)
        self.side_content.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.side_layout = QVBoxLayout(self.side_content)
        self.side_layout.setContentsMargins(0, 0, 0, 0)
        self.side_layout.setSpacing(2)
        self.side_layout.addStretch(1)
        self.side_content.hide()
        self.action_drawer = QWidget(self)
        self.action_drawer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        drawer = QVBoxLayout(self.action_drawer)
        drawer.setContentsMargins(0, 0, 0, 0)
        drawer.addWidget(self.shortcut_tabs)
        self.action_drawer.setMaximumHeight(0)
        layout.addWidget(self.action_drawer)
        self._arrange_sections('compact')
        self.drawer_animation = QPropertyAnimation(self.action_drawer, b'maximumHeight', self)
        self.drawer_animation.setDuration(140)
        self.drawer_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.drawer_animation.valueChanged.connect(self._drawer_frame)
        self.drawer_animation.finished.connect(self._screen_changed)
        self.dock_fade = QVariantAnimation(self)
        self.dock_fade.setDuration(220)
        self.dock_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.dock_fade.setEndValue(1.0)
        self.dock_fade.valueChanged.connect(self._fade_frame)
        self.dock_fade.finished.connect(lambda: self.card.setGraphicsEffect(None))
        self.drawer_delay = QTimer(self)
        self.drawer_delay.setSingleShot(True)
        self.drawer_delay.setInterval(200)
        self.drawer_delay.timeout.connect(self._collapse_actions)
        self._handles = {
            'right': DockHandle('right', 'Encaixar na lateral direita',
                                lambda: self.set_dock_mode('right'), self),
            'left': DockHandle('left', 'Encaixar na lateral esquerda',
                               lambda: self.set_dock_mode('left'), self),
            'top': DockHandle('up', 'Encaixar na parte superior',
                              lambda: self.set_dock_mode('top'), self),
            'back': DockHandle('left', 'Voltar ao widget compacto',
                               lambda: self.set_dock_mode('compact'), self),
        }
        self._place_handles()
        app = QGuiApplication.instance()
        app.installEventFilter(self)
        app.screenRemoved.connect(self._screen_changed)
        app.screenAdded.connect(self._watch_screen)
        for screen in app.screens():
            self._watch_screen(screen)

    def _arrange_sections(self, mode, target_width=None, target_height=None):
        side = mode in ('left', 'right')
        slim_top = mode == 'top' and (target_width or self.width()) >= SLIM_TOP_WIDTH
        short_side = side and (target_height or self.height()) < 700
        self.inner.removeWidget(self.mini_bar)
        self.mini_layout.removeWidget(self.navigation_group)
        for section in self._sections:
            self.inner.removeWidget(section)
            self.side_layout.removeWidget(section)
        for section in (self.gauge_widget, self.readings_widget, self.pause_button,
                        self.top_controls):
            self.inner.removeWidget(section)
        for row in range(6):
            self.inner.setRowStretch(row, 0)
        for column in range(5):
            self.inner.setColumnStretch(column, 0)
            self.inner.setColumnMinimumWidth(column, 0)
        for section in (self.gauge_widget, self.readings_widget):
            self.body_layout.removeWidget(section)
        if not slim_top:
            self.body_layout.addWidget(self.gauge_widget)
            self.body_layout.addWidget(self.readings_widget)
        for layout, saved in ((self.gauge_widget.layout(), self._gauge_margins),
                              (self.readings_layout, self._readings_margins)):
            margins = ((0, 0, 0, 0) if side or slim_top or mode == 'compact'
                       else (saved.left(), saved.top(), saved.right(), saved.bottom()))
            layout.setContentsMargins(*margins)
        self.body_layout.setSpacing(7 if mode == 'compact' else 10)
        self.body_layout.setDirection(QBoxLayout.Direction.TopToBottom if side
                                      else QBoxLayout.Direction.LeftToRight)
        self.body_layout.setStretch(1, 0 if side else 1)
        gauge_side = 60 if mode == 'compact' else 64 if slim_top else 68
        self.gauge.setFixedSize(gauge_side, gauge_side)
        self.ai_strip.layout().setDirection(QBoxLayout.Direction.TopToBottom if side
                                             else QBoxLayout.Direction.LeftToRight)
        self.shortcut_tabs.set_orientation(mode)
        for column in self.ai_strip.columns.values():
            self.ai_strip.layout().setAlignment(column, Qt.AlignmentFlag.AlignHCenter if side else Qt.AlignmentFlag(0))
            self.ai_strip.layout().setStretchFactor(column, 0 if side or slim_top else 1)
        for button in self.ai_strip.buttons.values():
            button.set_presentation(side)
        self.header_layout.removeWidget(self.brand)
        self.header_layout.removeWidget(self.keyboard_group)
        self.header_layout.removeWidget(self.navigation_group)
        self.gauge_widget.layout().removeWidget(self.brand)
        for section in (self.keyboard_group, self.navigation_group, self.pause_button):
            self.top_controls_layout.removeWidget(section)
        keyboard_button = self.shortcut_tabs.buttons['keyboard']
        for button, width in ((keyboard_button, 24 if side else 30),
                              (self.shortcut_tabs.top_button, 16 if side else 20),
                              (self.open_button, 32 if mode == 'mini' else 24 if side else 30),
                              (self.control_button, 32 if mode == 'mini' else 16 if side else 20)):
            button.setFixedSize(width, 32 if mode == 'mini' else 25 if side else 28)
        self.header_layout.setColumnStretch(0, 1)
        self.header_layout.setColumnStretch(1, 1 if side else 0)
        if side:
            self.header_layout.addWidget(self.brand, 0, 0, 1, 2, Qt.AlignmentFlag.AlignHCenter)
            self.header_layout.addWidget(self.keyboard_group, 1, 0, Qt.AlignmentFlag.AlignHCenter)
            self.header_layout.addWidget(self.navigation_group, 1, 1, Qt.AlignmentFlag.AlignHCenter)
        elif slim_top:
            self.gauge_widget.layout().insertWidget(0, self.brand)
            self.brand.show()
            self.top_controls_layout.addWidget(self.keyboard_group, 0, 0)
            self.top_controls_layout.addWidget(self.navigation_group, 0, 1)
            self.top_controls_layout.addWidget(self.pause_button, 1, 0, 1, 2,
                                               Qt.AlignmentFlag.AlignHCenter)
        elif mode == 'mini':
            self.mini_layout.addWidget(self.navigation_group)
        else:
            self.header_layout.addWidget(self.brand, 0, 0)
            self.header_layout.addWidget(self.keyboard_group, 0, 1)
            self.header_layout.addWidget(self.navigation_group, 0, 2)
        self.readings_layout.removeWidget(self.free_label)
        self.footer_layout.removeWidget(self.free_label)
        self.summary_row.removeWidget(self.free_label)
        self.notices_layout.removeWidget(self.pause_button)
        self.footer_layout.removeWidget(self.pause_button)
        if mode == 'compact':
            self.summary_row.addWidget(self.free_label)
        elif side:
            self.readings_layout.addWidget(self.free_label)
            self.notices_layout.addWidget(self.pause_button)
        elif slim_top:
            self.readings_layout.addWidget(self.free_label)
        else:
            self.footer_layout.insertWidget(0, self.pause_button)
            self.footer_layout.addWidget(self.free_label)
        self.footer_widget.setVisible(mode == 'top' and not slim_top)
        self.pause_button.setVisible(side or mode == 'top')
        self.monitoring_menu.menuAction().setVisible(mode == 'compact')
        self.theme_menu.menuAction().setVisible(mode == 'mini')
        self.body_layout.setAlignment(self.gauge_widget, Qt.AlignmentFlag.AlignHCenter if side else Qt.AlignmentFlag(0))
        for label in (self.status_label, self.alert_label, self.feedback_label):
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter if side else Qt.AlignmentFlag.AlignLeft)
        reading_alignment = (Qt.AlignmentFlag.AlignRight if mode == 'right' else
                             Qt.AlignmentFlag.AlignLeft)
        self.detail_label.setAlignment(reading_alignment)
        self.free_label.setAlignment(reading_alignment)
        for label in (self.detail_label, self.battery_label, self.free_label, self.alert_label):
            font = QFont(label.font())
            font.setPointSize(8 if short_side or slim_top else 9)
            label.setFont(font)
        self.free_label.setWordWrap(not slim_top and mode != 'compact')
        self.battery_label.setWordWrap(side)
        self.battery_label.setAlignment(reading_alignment)
        self.pause_button.setMinimumWidth(0)
        self.pause_button.setMaximumWidth(16777215)
        if slim_top:
            self.pause_button.setFixedWidth(100)
            self.readings_widget.setFixedWidth(330)
        else:
            self.readings_widget.setMinimumWidth(0)
            self.readings_widget.setMaximumWidth(16777215)
        self.pause_button.setSizePolicy(QSizePolicy.Policy.Expanding if side else QSizePolicy.Policy.Preferred,
                                        QSizePolicy.Policy.Preferred)
        self.battery_label.setVisible(bool(self._battery_text) and mode not in ('top', 'mini'))
        self._render_details()
        self.ai_strip.empty_label.setWordWrap(True)
        self.ai_strip.empty_label.setText('Sem cotas confirmadas' if mode in ('left', 'right')
                                          else 'Sem cotas disponíveis confirmadas')
        self.inner.setContentsMargins(16 if mode == 'left' else 6, 6,
                                      16 if mode == 'right' else 6, 2 if mode != 'compact' else 6)
        self.inner.setSpacing(2 if side else 3 if mode == 'compact' else 4)
        self.dock_scroll.setLayoutDirection(Qt.LayoutDirection.RightToLeft if mode == 'right'
                                             else Qt.LayoutDirection.LeftToRight)
        header, body, notices, ai, footer = self._sections
        if mode == 'mini':
            self.inner.addWidget(self.mini_bar, 0, 0)
        elif side:
            self.inner.addWidget(header, 0, 0)
            self.inner.addWidget(self.dock_scroll, 1, 0)
            self.inner.setRowStretch(1, 1)
            for row, section in enumerate((body, notices, ai)):
                self.side_layout.insertWidget(row, section)
        elif slim_top:
            self.inner.addWidget(self.gauge_widget, 0, 0, Qt.AlignmentFlag.AlignVCenter)
            self.inner.addWidget(ai, 0, 1, Qt.AlignmentFlag.AlignVCenter)
            self.inner.addWidget(self.readings_widget, 0, 2,
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.inner.addWidget(notices, 0, 3, Qt.AlignmentFlag.AlignVCenter)
            self.inner.addWidget(self.top_controls, 0, 4,
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            self.inner.setColumnMinimumWidth(4, 102)
            self.inner.setColumnStretch(3, 1)
        elif mode == 'top':
            self.inner.addWidget(header, 0, 0, Qt.AlignmentFlag.AlignVCenter)
            self.inner.addWidget(body, 0, 1, Qt.AlignmentFlag.AlignVCenter)
            self.inner.addWidget(footer, 0, 2, Qt.AlignmentFlag.AlignVCenter)
            self.inner.addWidget(ai, 1, 0, 1, 3, Qt.AlignmentFlag.AlignHCenter)
            self.inner.addWidget(notices, 2, 0, 1, 3)
            self.inner.setColumnStretch(1, 1)
        else:
            for row, section in enumerate(self._sections):
                self.inner.addWidget(section, row, 0)
        self.mini_bar.setVisible(mode == 'mini')
        self.header_widget.setVisible(mode != 'mini' and not slim_top)
        self.body_widget.setVisible(mode != 'mini' and not slim_top)
        self.notice_widget.setVisible(mode != 'mini')
        self.ai_strip.setVisible(mode != 'mini')
        self.gauge_widget.setVisible(mode != 'mini')
        self.readings_widget.setVisible(mode != 'mini')
        self.top_controls.setVisible(slim_top)

    def _sync_layout_actions(self):
        for mode, action in self.layout_actions.items():
            action.setChecked(mode == self._dock_mode)

    def _place_handles(self):
        width, height = self.width(), self.height()
        if self._dock_mode == 'mini':
            names = ()
        elif self._dock_mode == 'compact':
            self._handles['right'].setGeometry(0, 42, 16, max(38, height - 84))
            self._handles['left'].setGeometry(width - 16, 42, 16, max(38, height - 84))
            self._handles['top'].setGeometry((width - 60) // 2, 0, 60, 15)
            names = ('right', 'left', 'top')
        else:
            handle = self._handles['back']
            handle.arrow = {'right': 'left', 'left': 'right', 'top': 'down'}[self._dock_mode]
            content_bottom = height - self.action_drawer.maximumHeight()
            if self._dock_mode == 'right':
                handle.setGeometry(width - 16, 42, 16, max(38, content_bottom - 50))
            elif self._dock_mode == 'left':
                handle.setGeometry(0, 42, 16, max(38, content_bottom - 50))
            else:
                handle.setGeometry((width - 60) // 2, 0, 60, 15)
            names = ('back',)
        for name, handle in self._handles.items():
            if name in names:
                handle.show()
                handle.raise_()
            else:
                handle.hide()
                handle.hovered = False

    def _screen_area(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else QRect()

    def _set_card_scroll(self, mode):
        layout = self.layout()
        scroll = self.dock_scroll
        previous = scroll.takeWidget()
        if previous is self.side_content:
            self.side_content.setParent(self)
            self.side_content.hide()
        layout.removeWidget(scroll)
        self.inner.removeWidget(scroll)
        layout.removeWidget(self.card)
        scroll.setParent(self)
        if mode == 'top':
            scroll.setWidget(self.card)
            layout.insertWidget(0, scroll)
        else:
            layout.insertWidget(0, self.card)
            if mode in ('left', 'right'):
                scroll.setWidget(self.side_content)
                scroll.setParent(self.card)
                self.side_content.show()
        self.card.show()
        scroll.setVisible(mode not in FLOAT_MODES)

    def set_dock_mode(self, mode):
        if mode not in DOCK_MODES:
            raise ValueError('Modo de encaixe desconhecido')
        if mode == self._dock_mode or self._dock_pending or self._force_close:
            return
        if self._show_clamp_phase or self._dock_verify_phase:
            self._requested_mode = mode
            self._needs_show_reconcile = True
            return
        controller = self.shortcut_tabs.controller
        if controller.future is not None:
            self._shortcut_result('Aguarde a solicitação atual antes de encaixar o widget')
            return
        if mode not in FLOAT_MODES and not self._screen_area().isValid():
            self._shortcut_result('Área útil da tela indisponível')
            return
        if self._dock_mode in FLOAT_MODES and self._caps.session_type == 'wayland':
            self._dock_pending = mode
            if not controller.request('widget-geometry'):
                self._dock_pending = None
                self._shortcut_result('Posição atual do widget não confirmada')
            return
        self._apply_dock_mode(mode)

    def _apply_dock_mode(self, mode):
        controller = self.shortcut_tabs.controller
        previous = self._dock_mode
        if previous in FLOAT_MODES and self._caps.session_type != 'wayland':
            geometry = QRect(self.geometry())
            if previous == 'compact':
                self._compact_geometry = geometry
            else:
                self._mini_geometry = geometry
        origin = QRect(self.geometry())
        if mode in FLOAT_MODES:
            saved = self._compact_geometry if mode == 'compact' else self._mini_geometry
            if previous in FLOAT_MODES:
                confirmed = self._compact_geometry if previous == 'compact' else self._mini_geometry
                anchor = confirmed if self._caps.session_type == 'wayland' and confirmed else origin
            else:
                anchor = saved or self._compact_geometry or self._mini_geometry or origin
            target = QRect(anchor)
        else:
            target = dock_geometry(mode, self._screen_area())
        self.drawer_animation.stop()
        self.action_drawer.setMaximumHeight(0)
        self._dock_mode = mode
        self._sync_layout_actions()
        self._set_card_scroll(mode)
        self._arrange_sections(mode, target.width(), target.height())
        self.action_drawer.setMaximumHeight(0)
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        if mode in FLOAT_MODES:
            self.inner.activate()
            width = COMPACT_WIDTH if mode == 'compact' else self._mini_width()
            height = self.card.sizeHint().height() if mode == 'compact' else MINI_HEIGHT
            target = QRect(target.x(), target.y(), width, height)
            x, y = clamp_position(target.x(), target.y(), target.width(), target.height(), self._screens())
            target.moveTo(x, y)
            self._needs_compact_clamp = False
            self._dock_verify_attempts = 0
        if self._caps.session_type == 'wayland':
            self.setFixedSize(target.size())
        else:
            self.setGeometry(origin)
        self._place_handles()
        if self._caps.session_type == 'wayland':
            self.dock_fade.stop()
            self._dock_pending = mode
            effect = QGraphicsOpacityEffect(self.card)
            effect.setOpacity(0.55)
            self.card.setGraphicsEffect(effect)
            if not controller.request('widget-place', (target.x(), target.y(), target.width(), target.height())):
                self._dock_pending = None
                self.card.setGraphicsEffect(None)
                self._shortcut_result('Posicionamento não iniciado')
        else:
            if hasattr(self, 'dock_animation'):
                self.dock_animation.stop()
                self.dock_animation.deleteLater()
            self.dock_animation = QPropertyAnimation(self, b'geometry', self)
            self.dock_animation.setDuration(260)
            self.dock_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self.dock_animation.setStartValue(origin)
            self.dock_animation.setEndValue(target)
            self.dock_animation.finished.connect(lambda: self.setFixedSize(target.size())
                                                 if mode != 'compact' else self.setFixedWidth(COMPACT_WIDTH))
            self.dock_animation.finished.connect(self._schedule_mini_fit)
            self.dock_animation.start()
        self._dock_target = QRect(target) if mode not in FLOAT_MODES else None

    def _placement_done(self):
        self._dock_pending = None
        self._schedule_mini_fit()
        if self._dock_mode in FLOAT_MODES:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215 if self._dock_mode == 'compact' else MINI_HEIGHT)
            if self._dock_mode == 'compact' and self.height() < self.card.sizeHint().height():
                self.adjustSize()
        effect = self.card.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            self.dock_fade.setStartValue(effect.opacity())
            self.dock_fade.start()
        if self._needs_show_reconcile:
            QTimer.singleShot(0, self._reconcile_after_show)
        if self._dock_mode in FLOAT_MODES and self._needs_compact_clamp:
            QTimer.singleShot(80, self._reconcile_compact_after_show)
        if self._dock_mode not in FLOAT_MODES and self._dock_verify_attempts:
            QTimer.singleShot(180, self._verify_dock_after_show)

    def _fade_frame(self, value):
        effect = self.card.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(value)

    def _refresh_accounts_menu(self):
        from ..core import ai_sessions
        self.accounts_menu.clear()
        for provider, name in ai_sessions.NAMES.items():
            button = self.ai_strip.buttons[provider]
            left = button.remaining
            status = 'sem confirmação' if left is None else f'{left}% disponível'
            row = next((item for item in self.ai_strip.delivery_items
                        if item.get('provider') == provider), {})
            count = row.get('count')
            extras = [f'{count} entregas' if count != 1 else '1 entrega'] if count else []
            items = [item for item in self.ai_strip.items if item.get('provider') == provider]
            if provider == 'web':
                selected = next((item for item in items if item.get('default')), items[0] if items else {})
                service = (selected.get('web_service') or {}).get('state')
                tunnel = (selected.get('web_tunnel') or {}).get('state')
                status = ('serviço pronto' if service == 'ready' else
                          'serviço indisponível' if service == 'unavailable' else 'serviço desconhecido')
                extras.append('túnel local pronto' if tunnel == 'ready' else
                              'túnel local indisponível' if tunnel == 'unavailable' else 'túnel não confirmado')
                extras.append('limite desconhecido')
            tickets = sum(n for item in items if (n := ai_sessions.available_resets(item)) is not None and n > 0)
            if tickets:
                extras.append(f'{tickets} tickets')
            action = self.accounts_menu.addAction(' · '.join([name, status, *extras]))
            action.triggered.connect(lambda checked=False, p=provider: QTimer.singleShot(
                0, lambda: self.ai_strip.details(p, anchor=self.control_button)))

    def _sync_theme_menu(self):
        for action in self.theme_actions.actions():
            key = action.data()
            current = key == TOKENS.key
            action.setChecked(current)
            action.setText(THEMES[key].name + (' · em uso' if current else ''))

    def _theme_changed(self):
        self._sync_theme_menu()
        if self._dock_mode == 'compact' and self.isVisible():
            QTimer.singleShot(0, self, lambda: self._drawer_frame(None))
        else:
            self._schedule_mini_fit()

    def _change_theme(self, action):
        try:
            choose_theme(action.data())
        except (RuntimeError, ValueError) as error:
            self._sync_theme_menu()
            self._shortcut_result(str(error))

    def _animate_actions(self, expanded):
        if self._dock_mode == 'mini':
            self.action_drawer.setMaximumHeight(0)
            return
        self.drawer_animation.stop()
        self.drawer_animation.setStartValue(self.action_drawer.maximumHeight())
        self.drawer_animation.setEndValue(self.shortcut_tabs.sizeHint().height() if expanded else 0)
        self.drawer_animation.start()

    def _drawer_frame(self, value):
        self.layout().invalidate()
        if self._dock_mode == 'compact':
            self.adjustSize()
        else:
            self._place_handles()

    def enterEvent(self, event):
        self.drawer_delay.stop()
        self._animate_actions(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.drawer_delay.start()
        super().leaveEvent(event)

    def eventFilter(self, watched, event):
        # Qt/Wayland can synthesize an Enter on popup dismissal without pairing
        # its Leave when another surface of the same application is entered.
        if (event.type() == QEvent.Type.Enter and isinstance(watched, QWindow)
                and self.isVisible() and watched is not self.windowHandle()):
            self.drawer_delay.start()
        return super().eventFilter(watched, event)

    def _collapse_actions(self):
        popup = QApplication.activePopupWidget()
        if popup is not None and popup.isVisible():
            self.drawer_delay.start()
        else:
            # A new Enter cancels this timer; paired events own the hover state.
            self._animate_actions(False)

    def _shortcut_result(self, message):
        self.feedback_label.setText(message)
        self.feedback_label.show()
        self.feedback_timer.start(7000)
        if self._dock_mode == 'compact':
            self.adjustSize()
        elif self._dock_mode == 'mini':
            self._show_mini_feedback(message)

    def _show_mini_feedback(self, message):
        self.mini_status.setText('● Aviso')
        self.mini_status.setAccessibleName(f'Aviso do widget: {message}')
        self.mini_status.setToolTip(message)
        themed_style(self.mini_status, lambda: f'color:{TOKENS.warning};font-weight:700;')

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
        if value.get('operation') == 'widget-geometry' and self._dock_verify_phase == 'geometry':
            self._dock_verify_phase = None
            if self._requested_mode is not None and self._requested_mode != self._dock_mode:
                QTimer.singleShot(0, self._reconcile_after_show)
                return
            actual = value.get('geometry')
            if not isinstance(actual, tuple) or len(actual) != 4 or self._dock_mode in FLOAT_MODES:
                self._dock_verify_attempts = 0
                return
            target = dock_geometry(self._dock_mode, self._screen_area())
            expected = (target.x(), target.y(), target.width(), target.height())
            if all(abs(a - b) <= 1 for a, b in zip(actual, expected)):
                self._dock_verify_attempts = 0
                return
            self._dock_verify_attempts -= 1
            self._dock_verify_phase = 'place'
            if not self.shortcut_tabs.controller.request('widget-place', expected):
                self._dock_verify_phase = None
                self._dock_verify_attempts = 0
                self._shortcut_result('Encaixe do widget não restaurado')
            return
        if value.get('operation') == 'widget-place' and self._dock_verify_phase == 'place':
            self._dock_verify_phase = None
            if self._needs_show_reconcile:
                QTimer.singleShot(0, self._reconcile_after_show)
            elif self._dock_verify_attempts:
                QTimer.singleShot(180, self._verify_dock_after_show)
            return
        if value.get('operation') == 'widget-geometry' and self._show_clamp_phase == 'geometry':
            self._show_clamp_phase = None
            if self._requested_mode is not None and self._requested_mode != self._dock_mode:
                QTimer.singleShot(0, self._reconcile_after_show)
                return
            geometry = value.get('geometry')
            if (not isinstance(geometry, tuple) or len(geometry) != 4
                    or self._dock_mode not in FLOAT_MODES or not self.isVisible()):
                return
            x, y, width, height = geometry
            clamped = clamp_position(x, y, width, height, self._screens())
            if clamped != (x, y):
                self._show_clamp_phase = 'place'
                if not self.shortcut_tabs.controller.request(
                        'widget-place', (*clamped, width, height)):
                    self._show_clamp_phase = None
                    self._shortcut_result('Posição do widget flutuante não restaurada')
            return
        if value.get('operation') == 'widget-place' and self._show_clamp_phase == 'place':
            self._show_clamp_phase = None
            if self._needs_show_reconcile:
                QTimer.singleShot(0, self._reconcile_after_show)
            return
        if value.get('operation') == 'widget-geometry' and self._dock_pending:
            geometry = value.get('geometry')
            if isinstance(geometry, tuple) and len(geometry) == 4:
                mode, self._dock_pending = self._dock_pending, None
                current = QRect(*geometry)
                if self._dock_mode == 'compact':
                    self._compact_geometry = current
                else:
                    self._mini_geometry = current
                self._apply_dock_mode(mode)
            else:
                self._dock_pending = None
                self._shortcut_result('Posição atual do widget não confirmada')
        if value.get('operation') == 'widget-place' and self._dock_pending:
            self._placement_done()
        if value.get('operation') == 'capture-status' and not value['active']:
            self._finish_capture()

    def _capture_failed(self, _message):
        if self._dock_verify_phase and self.shortcut_tabs.controller.action in ('widget-geometry', 'widget-place'):
            self._dock_verify_phase = None
            self._dock_verify_attempts = 0
            self._shortcut_result('Posição da barra não confirmada')
            if self._needs_show_reconcile:
                QTimer.singleShot(0, self._reconcile_after_show)
            return
        if self._show_clamp_phase and self.shortcut_tabs.controller.action in ('widget-geometry', 'widget-place'):
            self._show_clamp_phase = None
            self._shortcut_result('Posição do widget flutuante não confirmada')
            if self._needs_show_reconcile:
                QTimer.singleShot(0, self._reconcile_after_show)
            return
        if self.shortcut_tabs.controller.action == 'widget-geometry' and self._dock_pending:
            self._dock_pending = None
            self._shortcut_result('Posição atual do widget não confirmada; encaixe não iniciado')
        if self.shortcut_tabs.controller.action == 'widget-place' and self._dock_pending:
            self._dock_pending = None
            self.card.setGraphicsEffect(None)
            self._schedule_mini_fit()
            if self._dock_verify_attempts:
                QTimer.singleShot(180, self._verify_dock_after_show)
            else:
                self._shortcut_result('Posição da barra não confirmada; confira a janela antes de tentar novamente')
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
        if self._dock_mode == 'compact':
            self.adjustSize()
        elif self._dock_mode == 'mini' and self._mini_latest is not None:
            self._render_mini(*self._mini_latest)

    # ------------------------------------------------------------------ reading

    def show_snapshot(self, snapshot, *, signal=None):
        signal = signal or title_signal.compute(snapshot)
        self.signal_label.setText(signal.text)
        from .dashboard_tab import headroom_pct
        self.gauge.set_state(headroom_pct(snapshot), signal.level)
        from .dashboard_tab import VERDICT
        verdict, role = VERDICT.get(signal.level, VERDICT["unknown"])
        self.status_label.setText(verdict)
        themed_style(self.status_label, lambda: f"color:{getattr(TOKENS, role)};font-weight:600;")
        memory = "RAM —"
        self.free_label.setText("RAM sem leitura")
        if snapshot.mem is not None and snapshot.mem.mem_total_kb > 0:
            used = 1 - snapshot.mem.mem_available_kb / snapshot.mem.mem_total_kb
            memory = f"RAM {used * 100:.0f}%"
            free = snapshot.mem.mem_available_kb / title_signal.MB
            self.free_label.setText(f"{title_signal.fmt1(free)} GB livres")
        cpu = "CPU —" if snapshot.cpu_busy_frac is None else f"CPU {snapshot.cpu_busy_frac * 100:.0f}%"
        swap = "Swap ?" if not snapshot.swap_known else "Swap —"
        if snapshot.swap_known and snapshot.swap_total_kb:
            swap = f"Swap {snapshot.swap_used_kb * 100 // snapshot.swap_total_kb}%"
        measured = [v for v in snapshot.tmpfs if v.quality == "ok" and v.total_bytes]
        temp = f"Tmp {max(v.used_frac for v in measured) * 100:.0f}%" if measured else "Tmp —"
        thermal = '— °C' if snapshot.temperature_c is None else f'{snapshot.temperature_c:.0f} °C'
        if snapshot.temperature_c is not None and snapshot.temperature_sensor == 'acpitz':
            thermal = f'ACPI {thermal}'
        fan = '— RPM' if snapshot.fan_rpm is None else f'{snapshot.fan_rpm} RPM'
        self._detail_values = memory, cpu, thermal, fan, swap, temp
        self._render_details()
        self._show_battery(snapshot)
        self.detail_label.setToolTip('CPU = uso agregado dos núcleos'
                                     + '\nTemperatura · ' + (snapshot.temperature_sensor or 'sensor não disponível')
                                     + (' (zona do sistema; não confirma temperatura da CPU)'
                                        if snapshot.temperature_sensor == 'acpitz' else '')
                                     + '\nCooler · ' + (snapshot.fan_sensor or 'RPM indisponível neste host')
                                     + '\nTmp = ocupação dos temporários em memória')
        alerts = []
        for volume in snapshot.tmpfs:
            if volume.quality != "ok":
                alerts.append(f"{volume.path}: capacidade desconhecida")
            elif volume.is_runtime and (volume.used_frac >= .9 or
                    (volume.inodes_total > 0 and volume.inodes_avail == 0)):
                alerts.append("Runtime crítico — aplicativos podem não abrir")
        degraded = [item.name for item in snapshot.sources
                    if item.status != "ok" and not (item.name in ('battery', 'external_power')
                                                    and item.status == 'missing')]
        if degraded:
            alerts.append("Coleta parcial: " + ", ".join(degraded[:3]))
        if signal.level == "unknown":
            alerts.append("Leitura desconhecida/antiga; aguardando nova observação")
        self.alert_label.setText("\n".join(alerts))
        self.alert_label.setVisible(bool(alerts))
        self._mini_latest = (snapshot, signal, tuple(alerts))
        self._render_mini(snapshot, signal, alerts)
        self._sync_tooltip()
        if self._dock_mode == 'compact':
            self.adjustSize()
        self._screen_changed()

    def _render_mini(self, snapshot, signal, alerts):
        from .dashboard_tab import VERDICT, usage_level
        thresholds = getattr(self._window, '_thresholds', title_signal.Thresholds())
        verdict, role = VERDICT.get(signal.level, VERDICT['unknown'])
        verdict = {'Saudável': 'OK', 'Desconhecido': 'Sem dados'}.get(verdict, verdict)
        stale = snapshot.is_stale(thresholds.stale_after_s)
        valid = not stale and not self._paused
        temperature = (snapshot.temperature_c if valid and
                       snapshot.source('temperature').status == 'ok' else None)
        if temperature is not None and not math.isfinite(temperature):
            temperature = None
        thermal_notes = []
        limit = snapshot.thermal_passive_c or snapshot.thermal_critical_c
        if limit is not None and not math.isfinite(limit):
            limit = None
        temperature_role = 'muted'
        if temperature is not None and limit is not None:
            temperature_role = 'ok'
            if snapshot.thermal_critical_c is not None and temperature >= snapshot.thermal_critical_c:
                thermal_notes.append('Limite térmico crítico observado')
                temperature_role = 'danger'
            elif temperature >= limit:
                thermal_notes.append('Limite térmico passivo observado')
                temperature_role = 'danger'
            elif temperature >= limit - thresholds.thermal_margin_c:
                thermal_notes.append('Temperatura próxima do limite passivo')
                temperature_role = 'warning'
        battery_ok = (valid and snapshot.battery is not None
                      and snapshot.source('battery').status == 'ok')
        battery_sag = battery_ok and voltage_sag(snapshot.battery)
        battery_low = battery_ok and (battery_sag or (
            snapshot.battery.status == 'Discharging' and snapshot.battery.percent <= 10))
        if battery_sag:
            thermal_notes.append(f'Voltagem da bateria baixa ({voltage_text(snapshot.battery)}) '
                                 f'apesar de {snapshot.battery.percent}%: risco de desligamento')
        elif battery_low:
            thermal_notes.append(f'Bateria em {snapshot.battery.percent}%, descarregando')
        if self._paused:
            verdict, role = 'Pausado', 'muted'
        elif temperature is not None and limit is not None and temperature >= limit - thresholds.thermal_margin_c:
            if snapshot.thermal_critical_c is not None and temperature >= snapshot.thermal_critical_c:
                verdict, role = 'Crítico', 'danger'
            elif limit is not None and temperature >= limit:
                verdict, role = 'Calor alto', 'danger'
            elif limit is not None and temperature >= limit - thresholds.thermal_margin_c:
                verdict, role = 'Quente', 'warning'
        elif battery_sag:
            verdict, role = f'Bateria {voltage_text(snapshot.battery)}', 'danger'
        elif battery_low:
            verdict, role = f'Bateria {snapshot.battery.percent}%', 'danger'
        self.mini_status.setText(f'● {verdict}')
        self.mini_status.setAccessibleName(f'Estado do Fôlego: {verdict}')
        themed_style(self.mini_status, lambda: f'color:{getattr(TOKENS, role)};font-weight:700;')
        cpu = (snapshot.cpu_busy_frac if valid and snapshot.source('cpu').status == 'ok'
               else None)
        memory = (snapshot.mem if valid and snapshot.source('meminfo').status == 'ok'
                  else None)
        cpu_role = 'muted'
        if cpu is not None and math.isfinite(cpu) and 0 <= cpu <= 1:
            level = usage_level(cpu, warning=.75, critical=.95)
            cpu_role = {'ok': 'ok', 'atenção': 'warning', 'crítico': 'danger'}[level]
        else:
            cpu = None
        self._set_mini_metric(self.mini_cpu, f'{cpu * 100:.0f}%' if cpu is not None else '—',
                              cpu_role)
        memory_role, memory_text = 'muted', '—'
        if memory is not None and 0 <= memory.mem_available_kb <= memory.mem_total_kb and memory.mem_total_kb > 0:
            available = memory.mem_available_kb / memory.mem_total_kb
            memory_text = f'{(1 - available) * 100:.0f}%'
            memory_role = ('danger' if available < thresholds.red_available_frac else
                           'warning' if available < thresholds.yellow_available_frac else 'ok')
        self._set_mini_metric(self.mini_memory, memory_text, memory_role)
        battery = (snapshot.battery if valid and snapshot.source('battery').status == 'ok'
                   else None)
        self.mini_battery_cell.setVisible(snapshot.battery is not None
                                          or snapshot.source('battery').status not in ('missing', 'unsupported'))
        battery_role = 'muted'
        if battery is not None:
            battery_role = {'green': 'ok', 'yellow': 'warning', 'orange': 'warning',
                            'red': 'danger'}[battery_band(battery.percent)]
        self._set_mini_metric(self.mini_battery, f'{battery.percent}%' if battery else '—',
                              battery_role, color=self._battery_color if battery else None)
        if battery:
            tip = self._battery_text + '\n' + self.battery_label.toolTip()
            if self._voltage_text:
                self.mini_battery.setAccessibleDescription(
                    f'{self.mini_battery.accessibleDescription()} · voltagem {self._voltage_text}')
            self.mini_battery.setToolTip(tip)
            self.mini_voltage.setToolTip(tip)
        self.mini_voltage.setText(self._voltage_text.replace(' ', '') if battery else '')
        self.mini_voltage.setVisible(bool(battery and self._voltage_text))
        themed_style(self.mini_voltage, lambda: 'background:transparent;'
                     f'color:{self._band_color(self._voltage_band)};font-size:9pt;font-weight:700;')
        self._schedule_mini_fit()
        source = ('ACPI' if snapshot.temperature_sensor == 'acpitz'
                  else snapshot.temperature_sensor)
        self.mini_temperature_caption.setText('ACPI' if source == 'ACPI' else 'TEMP')
        self._set_mini_metric(self.mini_temperature,
                              f'{temperature:.0f} °C' if temperature is not None else '— °C',
                              temperature_role)
        self.mini_cpu.setToolTip(
            f'Uso agregado dos núcleos · {self.mini_cpu.accessibleDescription()}\n'
            'Atenção a partir de 75%; crítico a partir de 95%.')
        self.mini_memory.setToolTip(
            f'RAM usada · {self.mini_memory.accessibleDescription()}\n'
            f'Atenção com menos de {thresholds.yellow_available_frac * 100:g}% livre; '
            f'crítico com menos de {thresholds.red_available_frac * 100:g}% livre.')
        thermal_detail = (f'Limite do sensor {limit:g} °C' if limit is not None
                          else 'Limite do sensor indisponível; criticidade desconhecida')
        self.mini_temperature.setToolTip(
            f'Temperatura · {snapshot.temperature_sensor or "sensor indisponível"}\n'
            f'{self.mini_temperature.accessibleDescription()} · {thermal_detail}'
            + ('\nZona térmica do sistema (ACPI)' if source == 'ACPI' else ''))
        self.mini_status.setToolTip('\n'.join([signal.text, *thermal_notes, *alerts]))
        if self._dock_mode == 'mini' and self.feedback_label.isVisible():
            self._show_mini_feedback(self.feedback_label.text())

    def _set_mini_metric(self, label, text, role, *, color=None):
        state = {'ok': 'Normal', 'warning': 'Atenção', 'danger': 'Crítico',
                 'muted': 'Sem avaliação válida'}[role]
        label.setText(text)
        label.setProperty('level', role)
        label.setAccessibleDescription(f'{text} · {state}')
        label.setToolTip(f'{label.accessibleName()} · {label.accessibleDescription()}')
        themed_style(label, lambda: f'background:transparent;color:{color() if color else getattr(TOKENS, role)};'
                     'font-size:9pt;font-weight:600;')

    def _mini_account_details(self, provider, account, anchor):
        self.ai_strip.details(provider, anchor=anchor)
        if account and self.ai_strip.account_panel is not None:
            self.ai_strip.account_panel.select(account)

    def _mini_width(self):
        self.mini_layout.invalidate()
        self.inner.invalidate()
        return min(self._screen_area().width(), max(MINI_WIDTH, self.card.minimumSizeHint().width()))

    def _schedule_mini_fit(self):
        if self._dock_mode == 'mini':
            self.mini_fit_timer.start(0)

    def _fit_mini(self):
        if self._dock_mode != 'mini' or self._dock_pending:
            return
        width = self._mini_width()
        if self.width() != width:
            self.setFixedWidth(width)
            self._screen_changed()

    def _render_details(self):
        if not hasattr(self, '_detail_values'):
            return
        memory, cpu, thermal, fan, swap, temp = self._detail_values
        if self._dock_mode in ('left', 'right'):
            self.detail_label.setTextFormat(Qt.TextFormat.PlainText)
            self.detail_label.setText('\n'.join((memory, cpu, thermal, fan, swap, temp)))
        else:
            battery = self._battery_html() if self._dock_mode == 'top' else ''
            self.detail_label.setTextFormat(Qt.TextFormat.RichText)
            if self._dock_mode == 'compact':
                self.detail_label.setText('<table width="100%" cellspacing="0"><tr>'
                    f'<td>{memory}</td><td align="right">{cpu}</td></tr>'
                    f'<tr><td>{swap}</td><td align="right">{temp}</td></tr>'
                    f'<tr><td>{thermal}</td><td align="right">{fan}</td></tr></table>')
            else:
                self.detail_label.setText('<table width="100%" cellspacing="0"><tr>'
                    f'<td>{memory}</td><td>{cpu}</td><td>{thermal} · {fan}</td></tr>'
                    f'<tr><td>{swap}</td><td>{temp}</td><td>{battery}</td></tr></table>')

    def _band_color(self, band):
        return {'green': TOKENS.ok, 'yellow': readable('#e8bd18', (TOKENS.surface, TOKENS.surface_alt)),
                'orange': readable('#ef8625', (TOKENS.surface, TOKENS.surface_alt)),
                'red': TOKENS.danger, None: TOKENS.muted}[band]

    def _battery_color(self):
        return self._band_color(self._battery_band)

    def _voltage_html(self, text=None):
        """Voltage in its own level colour; muted when the level is unknown."""
        return (f'<span style="color:{self._band_color(self._voltage_band)};font-weight:700">'
                f'{text or self._voltage_text}</span>')

    def _battery_html(self):
        html = f'<span style="color:{self._battery_color()};font-weight:700">{self._battery_text}</span>'
        return html + (' · ' + self._voltage_html() if self._voltage_text else '')

    def _battery_style(self):
        return f'color:{self._battery_color()};font-weight:700;'

    def _show_battery(self, snapshot, *, now_mono=None):
        battery = (snapshot.battery if snapshot.source('battery').status == 'ok'
                   and not snapshot.is_stale(15.0, now_mono) else None)
        if battery is None:
            self._battery_text = self._voltage_text = ''
            self._voltage_band = None
            self.battery_label.hide()
            if self._dock_mode == 'top':
                self._render_details()
            return
        self._battery_band = battery_band(battery.percent)
        self.battery_label.setStyleSheet(self._battery_style())
        suffix = {'Charging': ' · carregando', 'Full': ' · cheia',
                  'Not charging': ' · conectada'}.get(battery.status, '')
        estimate = remaining_text(battery.remaining_s) if battery.status == 'Discharging' else ''
        self._battery_text = f'Bat {battery.percent}%{suffix}' + (f' · ~{estimate}' if estimate else '')
        level = voltage_level(battery)
        self._voltage_band = VOLTAGE_BANDS.get(level)
        self._voltage_text = voltage_text(battery) if battery.voltage_uv is not None else ''
        self.battery_label.setTextFormat(Qt.TextFormat.RichText)
        self.battery_label.setText(self._battery_html())
        tip = ('Bateria · estimativa variável com o consumo' if estimate
               else 'Bateria · tempo restante não disponível')
        if self._voltage_text:
            tip += (f'\nVoltagem {self._voltage_text} · {VOLTAGE_NAMES[level]}' if level else
                    f'\nVoltagem {self._voltage_text} · sem avaliação fora da descarga'
                    if battery.status != 'Discharging' else
                    f'\nVoltagem {self._voltage_text} · sem referência de projeto')
            if level == 'critical':
                tip += ' · risco de desligamento: conecte o carregador e reduza a carga'
        self.battery_label.setToolTip(tip)
        self.battery_label.setVisible(self._dock_mode not in ('top', 'mini'))
        if self._dock_mode == 'top':
            self._render_details()

    def _sync_tooltip(self):
        self.setToolTip("\n".join(text for text in (
            self.signal_label.text(), self.mode_label.text(), self.operation_label.text(),
            self.alert_label.text(), self.feedback_label.text() if self.feedback_label.isVisible() else '',
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
        changed = bool(paused) != self._paused
        self._paused = bool(paused)
        self.pause_button.setText("Retomar" if paused else "Pausar")
        self.pause_button.setToolTip("Retomar monitoramento" if paused else "Pausar monitoramento")
        self.pause_action.setText(self.pause_button.toolTip())
        self.pause_button.setAccessibleDescription("monitoramento pausado" if paused else "monitoramento ativo")
        self._render_mode()
        if changed:
            state = 'Pausado' if paused else 'Aguardando'
            self.mini_status.setText(f'● {state}')
            self.mini_status.setAccessibleName(f'Estado do Fôlego: {state}')
            themed_style(self.mini_status, lambda: f'color:{TOKENS.muted};font-weight:700;')
            for label, text in ((self.mini_cpu, '—'),
                                (self.mini_temperature, '— °C'),
                                (self.mini_memory, '—'), (self.mini_battery, '—')):
                self._set_mini_metric(label, text, 'muted')

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
        if self._dock_mode not in FLOAT_MODES or not self._caps.absolute_position:
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
        if self._dock_mode not in FLOAT_MODES or not self._caps.absolute_position:
            return
        point = self.pos()
        self._store.setValue(POSITION_KEY, f"{point.x()},{point.y()}")
        sync = getattr(self._store, "sync", None)
        if sync is not None:
            sync()

    def show_compact(self, desired_mode=None):
        if desired_mode is not None and desired_mode not in DOCK_MODES:
            raise ValueError('Modo de widget desconhecido')
        self._restore_position()
        self.show()
        self.raise_()
        if self._caps.session_type == 'wayland':
            self._dock_verify_attempts = 3 if (desired_mode in ('left', 'right', 'top')
                                                 or desired_mode is None and self._dock_mode not in FLOAT_MODES) else 0
            self._dock_verify_waits = 0
        if self._caps.session_type == 'wayland' and desired_mode in (None, *FLOAT_MODES):
            self._needs_compact_clamp = True
            QTimer.singleShot(80, self._reconcile_compact_after_show)
        if desired_mode is not None:
            self._requested_mode = desired_mode
        if self._dock_mode not in FLOAT_MODES or self._requested_mode is not None:
            self._needs_show_reconcile = True
            QTimer.singleShot(0, self._reconcile_after_show)

    def _reconcile_after_show(self):
        """KWin may reapply the floating position rule when a dock is remapped."""
        if (not self._needs_show_reconcile or not self.isVisible() or self._force_close
                or self._dock_pending or self.shortcut_tabs.controller.future is not None):
            return
        self._needs_show_reconcile = False
        requested, self._requested_mode = self._requested_mode, None
        if requested is not None and requested != self._dock_mode:
            self.set_dock_mode(requested)
            return
        if self._dock_mode in FLOAT_MODES:
            return
        target = dock_geometry(self._dock_mode, self._screen_area())
        self._dock_target = QRect(target)
        if self._caps.session_type != 'wayland':
            self.setGeometry(target)
            return
        self._dock_pending = self._dock_mode
        if not self.shortcut_tabs.controller.request('widget-place',
                (target.x(), target.y(), target.width(), target.height())):
            self._dock_pending = None
            self._dock_verify_attempts = 0
            self._shortcut_result('Não foi possível restaurar a posição da barra')

    def _verify_dock_after_show(self):
        if not self._dock_verify_attempts or self._dock_mode in FLOAT_MODES or self._force_close:
            return
        surface = self.windowHandle()
        if (not self.isVisible() or surface is None or not surface.isExposed()
                or not self._screen_area().isValid()
                or self._dock_pending or self._dock_verify_phase
                or self.shortcut_tabs.controller.future is not None):
            self._dock_verify_waits += 1
            if self._dock_verify_waits <= 40:
                QTimer.singleShot(100, self._verify_dock_after_show)
            else:
                self._dock_verify_attempts = 0
                self._shortcut_result('Encaixe sem confirmação após aguardar o controlador')
            return
        self._dock_verify_waits = 0
        self._dock_verify_phase = 'geometry'
        if not self.shortcut_tabs.controller.request('widget-geometry'):
            self._dock_verify_phase = None
            self._dock_verify_attempts = 0
            self._shortcut_result('Posição da barra não confirmada')

    def _reconcile_compact_after_show(self):
        if (not self._needs_compact_clamp or not self.isVisible() or self._force_close
                or self._dock_mode not in FLOAT_MODES or not self._screen_area().isValid()
                or self._dock_pending or self._show_clamp_phase
                or self.shortcut_tabs.controller.future is not None):
            return
        self._needs_compact_clamp = False
        self._show_clamp_phase = 'geometry'
        if not self.shortcut_tabs.controller.request('widget-geometry'):
            self._show_clamp_phase = None
            self._shortcut_result('Posição do widget flutuante não confirmada')

    def _watch_screen(self, screen):
        screen.availableGeometryChanged.connect(self._screen_changed)
        self._screen_changed()

    def _screen_changed(self, *_args):
        if self._dock_mode == 'mini' and not self._dock_pending:
            self.setFixedWidth(self._mini_width())
        if self._dock_mode not in FLOAT_MODES:
            area = self._screen_area()
            if not area.isValid() or self._dock_pending:
                return
            target = dock_geometry(self._dock_mode, area)
            if self._dock_target == target:
                return
            if self._caps.session_type == 'wayland' and self.shortcut_tabs.controller.future is not None:
                return
            self._dock_target = QRect(target)
            self._arrange_sections(self._dock_mode, target.width(), target.height())
            self.setFixedSize(target.size())
            if self._caps.session_type == 'wayland':
                if self.shortcut_tabs.controller.future is None:
                    self._dock_pending = self._dock_mode
                    if not self.shortcut_tabs.controller.request('widget-place',
                            (target.x(), target.y(), target.width(), target.height())):
                        self._dock_pending = None
            else:
                self.move(target.topLeft())
            return
        if self.isVisible() and self._caps.session_type == 'wayland':
            self._needs_compact_clamp = True
            QTimer.singleShot(80, self._reconcile_compact_after_show)
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
        if self._dock_mode not in FLOAT_MODES:
            super().mousePressEvent(event)
            return
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0, 0, -1, -1), 12, 12)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        if hasattr(self, '_handles'):
            self._place_handles()

    def hideEvent(self, event):
        self.drawer_delay.stop()
        self.drawer_animation.stop()
        self.action_drawer.setMaximumHeight(0)
        self._save_position()
        super().hideEvent(event)

    def closeEvent(self, event):
        if self._force_close:
            super().closeEvent(event)
            return
        self._save_position()
        event.ignore()
        self._hide_safely()
