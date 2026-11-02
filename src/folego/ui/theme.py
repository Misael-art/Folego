"""One live theme authority for every Qt surface, with persistent selection."""
from PySide6.QtCore import QSettings, QObject, QEvent, Qt
from PySide6.QtGui import QColor, QPalette, QIcon, QPainter
from PySide6.QtWidgets import QApplication, QWidget, QStyle, QStyleOption, QDialog
from .palettes import THEMES, DEFAULT_THEME, Tokens, on_color

THEME_KEY = 'appearance/theme'
TRANSPARENCY_KEY = 'appearance/background_transparency'


class _ActiveTokens:
    # Imports keep this identity. Replacing a palette never strands old imports.
    current = THEMES[DEFAULT_THEME].tokens
    key = DEFAULT_THEME
    transparency = 0

    def __getattr__(self, name):
        return getattr(self.current, name)


TOKENS = _ActiveTokens()


def background(color):
    """Alpha belongs to surface paint, never to a whole window or its content."""
    if TOKENS.transparency == 0: return color
    value = QColor(color)
    return f'rgba({value.red()},{value.green()},{value.blue()},{round(255 * (100 - TOKENS.transparency) / 100)})'


def _background_color(color):
    value = QColor(color)
    value.setAlpha(round(255 * (100 - TOKENS.transparency) / 100))
    return value


def prepare_surface(widget):
    # Must precede native surface creation; toggling after mapping is unreliable.
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def paint_surface(widget):
    """Translucent roots skip Qt's automatic background; paint their QSS once."""
    if widget.testAttribute(Qt.WidgetAttribute.WA_NoSystemBackground):
        option = QStyleOption()
        option.initFrom(widget)
        painter = QPainter(widget)
        widget.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, widget)
        painter.end()


class _SurfacePreparation(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Polish and isinstance(watched, QWidget) and watched.isWindow():
            prepare_surface(watched)
        elif event.type() == QEvent.Type.Paint and isinstance(watched, QDialog):
            paint_surface(watched)
        return False


def themed_style(widget, factory):
    """Keep the recipe on its owner, never a global strong reference to a widget."""
    widget._folego_theme_style = factory
    widget.setStyleSheet(factory())


def on_theme_change(widget, callback):
    callbacks = getattr(widget, '_folego_theme_callbacks', [])
    widget._folego_theme_callbacks = [*callbacks, callback]


def shortcut_style(index):
    color = TOKENS.actions[index]
    ink = on_color(color)
    return (f'QPushButton{{background:{background(color)};color:{ink};border:1px solid {color};border-radius:5px;'
            'font-size:8pt;padding:1px;min-height:18px;}'
            f'QPushButton:hover{{border-color:{TOKENS.text};}}'
            f'QPushButton:focus{{border:2px solid {TOKENS.focus};padding:0;}}'
            f'QPushButton:disabled{{background:{background(TOKENS.surface_alt)};color:{TOKENS.muted};border-color:{TOKENS.border};}}')


def tint_icon(icon):
    pixmap = icon.pixmap(16, 16)
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(TOKENS.text))
    painter.end()
    return QIcon(pixmap)


def set_control_icon(widget, name, fallback, *, fallback_icon=None):
    def refresh():
        widget.setIcon(control_icon(widget.style(), name, fallback, fallback_icon=fallback_icon))
    on_theme_change(widget, refresh)
    refresh()


def control_icon(style, name, fallback, *, fallback_icon=None):
    """Native theme/Qt icons with a readable monochrome mask on dark surfaces."""
    icon = QIcon.fromTheme(name, fallback_icon if fallback_icon is not None else style.standardIcon(fallback))
    return tint_icon(icon)

def stylesheet():
    return f"""
QWidget {{
    background-color: transparent;
    color: {TOKENS.text};
    selection-background-color: {TOKENS.accent};
    selection-color: {TOKENS.accent_text};
}}
QMainWindow, QDialog {{
    background-color: {background(TOKENS.background)};
}}
QTabWidget::pane, QScrollArea {{
    background: transparent;
}}
QTabWidget::pane {{
    border: 1px solid {TOKENS.border};
    border-radius: {TOKENS.radius}px;
    top: -1px;
}}
QTabBar::tab {{
    background: {background(TOKENS.surface)};
    color: {TOKENS.muted};
    padding: 7px 14px;
    margin-right: 2px;
    border: 1px solid {TOKENS.border};
    border-bottom: none;
    border-top-left-radius: {TOKENS.radius}px;
    border-top-right-radius: {TOKENS.radius}px;
}}
QTabBar::tab:selected {{
    background: {background(TOKENS.surface_alt)};
    color: {TOKENS.text};
    border-bottom: 2px solid {TOKENS.accent};
}}
QTabBar::tab:focus {{
    border: 2px solid {TOKENS.focus};
}}
QTabWidget#sidebar::pane {{
    border: none;
    border-left: 1px solid {TOKENS.border};
    border-radius: 0;
}}
QTabWidget#sidebar QTabBar::tab {{
    min-width: 128px;
    padding: 8px 16px;
    margin: 2px 6px 2px 0;
    border: none;
    border-left: 3px solid transparent;
    border-radius: {TOKENS.radius}px;
    text-align: left;
}}
QTabWidget#sidebar QTabBar::tab:selected {{
    background: {background(TOKENS.surface_alt)};
    color: {TOKENS.text};
    border-left: 3px solid {TOKENS.accent};
}}
QTabWidget#sidebar QTabBar::tab:focus {{
    border: 2px solid {TOKENS.focus};
}}
QFrame#hero, QFrame#card {{
    background: {background(TOKENS.surface)};
    border: 1px solid {TOKENS.border};
    border-radius: {TOKENS.radius * 2}px;
}}
QFrame#hero QLabel, QFrame#card QLabel, QFrame#card QProgressBar {{
    background: transparent;
}}
QFrame#card[level="warning"] {{
    border-color: {TOKENS.warning};
}}
QFrame#card[level="danger"] {{
    border-color: {TOKENS.danger};
}}
QLabel#cardTitle {{
    color: {TOKENS.muted};
    font-weight: 600;
}}
QLabel#cardValue {{
    font-size: 20pt;
    font-weight: 600;
}}
QLabel#section {{
    color: {TOKENS.muted};
    font-weight: 600;
    font-size: 11pt;
}}
QPushButton#pill {{
    background: {background(TOKENS.surface_alt)};
    color: {TOKENS.text};
    border: 1px solid {TOKENS.accent};
    border-radius: 16px;
    padding: 7px 16px;
    font-weight: 600;
}}
QPushButton#pill:hover {{
    background: {TOKENS.accent};
    color: {TOKENS.accent_text};
}}
QPushButton#primary {{
    background: {TOKENS.accent};
    color: {TOKENS.accent_text};
    border: 1px solid {TOKENS.accent};
    font-weight: 600;
    padding: 9px 18px;
}}
QPushButton#primary:disabled {{
    background: {background(TOKENS.surface_alt)};
    color: {TOKENS.muted};
    border-color: {TOKENS.border};
}}
QFrame#card[level="warning"] QProgressBar::chunk {{
    background: {TOKENS.warning};
}}
QFrame#card[level="danger"] QProgressBar::chunk {{
    background: {TOKENS.danger};
}}
QFrame#card[level="ok"] QProgressBar::chunk {{
    background: {TOKENS.ok};
}}
QLabel#headline {{
    font-size: 16pt;
    font-weight: 600;
    color: {TOKENS.text};
}}
QLabel#why {{
    color: {TOKENS.muted};
}}
QLabel#quality {{
    color: {TOKENS.muted};
}}
QLabel#danger {{
    color: {TOKENS.danger};
}}
QLabel#warning {{
    color: {TOKENS.warning};
}}
QPushButton {{
    background: {background(TOKENS.surface_alt)};
    color: {TOKENS.text};
    border: 1px solid {TOKENS.border};
    border-radius: {TOKENS.radius}px;
    padding: 5px 11px;
    min-height: 24px;
}}
QPushButton:hover {{
    border-color: {TOKENS.accent};
}}
QPushButton:focus {{
    border: 2px solid {TOKENS.focus};
}}
QPushButton:disabled {{
    color: {TOKENS.muted};
    border-color: {TOKENS.border};
    background: {background(TOKENS.surface)};
}}
QPushButton:default {{
    border-color: {TOKENS.accent};
}}
QTableWidget, QTreeWidget, QListView {{
    background: {background(TOKENS.surface)};
    alternate-background-color: {background(TOKENS.surface_alt)};
    gridline-color: {TOKENS.border};
    border: 1px solid {TOKENS.border};
    border-radius: {TOKENS.radius}px;
}}
QHeaderView::section {{
    background: {background(TOKENS.surface_alt)};
    color: {TOKENS.muted};
    border: none;
    border-bottom: 1px solid {TOKENS.border};
    padding: 4px 6px;
}}
QTableWidget:focus, QTreeWidget:focus {{
    border: 2px solid {TOKENS.focus};
}}
QProgressBar {{
    background: {background(TOKENS.surface_alt)};
    border: 1px solid {TOKENS.border};
    border-radius: {TOKENS.radius}px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {TOKENS.accent};
    border-radius: {TOKENS.radius - 1}px;
}}
QMenu {{background:{background(TOKENS.surface)};color:{TOKENS.text};border:1px solid {TOKENS.border};}}
QMenu::item:selected {{background:{TOKENS.accent};color:{TOKENS.accent_text};}}
QMenu::item:disabled {{color:{TOKENS.muted};}}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background:{background(TOKENS.surface)};color:{TOKENS.text};border:1px solid {TOKENS.border};
    border-radius:4px;padding:4px;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{border:2px solid {TOKENS.focus};}}
QGroupBox {{border:1px solid {TOKENS.border};border-radius:6px;margin-top:12px;padding-top:12px;}}
QGroupBox::title {{subcontrol-origin:margin;left:8px;padding:0 4px;}}
QCheckBox::indicator:unchecked {{width:14px;height:14px;border:1px solid {TOKENS.border};border-radius:3px;background:{background(TOKENS.surface_alt)};}}
QSlider::groove:horizontal {{height:4px;background:{TOKENS.border};border-radius:2px;}}
QSlider::handle:horizontal {{width:14px;margin:-5px 0;background:{TOKENS.accent};border:1px solid {TOKENS.text};border-radius:7px;}}
QToolTip {{
    background: {background(TOKENS.surface_alt)};
    color: {TOKENS.text};
    border: 1px solid {TOKENS.focus};
    padding: 4px;
}}
"""


STYLESHEET = stylesheet()


def _transparency(value):
    if isinstance(value, str) and value.isascii() and value.isdigit(): value = int(value)
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError('Transparência salva desconhecida; escolha um valor entre 0 e 100%.')
    return value


def apply_theme(app: QApplication | None = None, theme_id: str | None = None, *, store=None,
                transparency: int | None = None) -> None:
    app = app or QApplication.instance()
    if app is None:
        return
    if theme_id is None:
        store = store if store is not None else QSettings('folego', 'folego')
        saved = store.value(THEME_KEY, DEFAULT_THEME)
        theme_id = saved if isinstance(saved, str) and saved in THEMES else DEFAULT_THEME
        errors = [] if theme_id == saved else ['Tema salvo desconhecido; escolha um tema para salvar a preferência.']
        try: transparency = _transparency(store.value(TRANSPARENCY_KEY, 0))
        except ValueError as exc:
            transparency = 0; errors.append(str(exc))
        if store.status() != QSettings.Status.NoError:
            errors.append('Preferências não puderam ser lidas completamente; confira a configuração.')
        app.setProperty('folego_theme_error', ' '.join(errors))
    if theme_id not in THEMES:
        raise ValueError('Tema desconhecido')
    transparency = TOKENS.transparency if transparency is None else _transparency(transparency)
    TOKENS.current = THEMES[theme_id].tokens
    TOKENS.key = theme_id
    TOKENS.transparency = transparency
    if not hasattr(app, '_folego_surface_preparation'):
        app._folego_surface_preparation = _SurfacePreparation(app)
        app.installEventFilter(app._folego_surface_preparation)
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, _background_color(TOKENS.background))
    palette.setColor(QPalette.ColorRole.Base, _background_color(TOKENS.surface))
    palette.setColor(QPalette.ColorRole.AlternateBase, _background_color(TOKENS.surface_alt))
    palette.setColor(QPalette.ColorRole.Text, QColor(TOKENS.text))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TOKENS.text))
    palette.setColor(QPalette.ColorRole.Button, _background_color(TOKENS.surface_alt))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TOKENS.text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(TOKENS.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TOKENS.accent_text))
    palette.setColor(QPalette.ColorRole.ToolTipBase, _background_color(TOKENS.surface_alt))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TOKENS.text))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TOKENS.muted))
    palette.setColor(QPalette.ColorRole.Link, QColor(TOKENS.accent))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor(TOKENS.accent))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(TOKENS.muted))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet())
    for widget in app.allWidgets():
        factory = getattr(widget, '_folego_theme_style', None)
        if factory is not None:
            style = factory()
            if style != widget.styleSheet(): widget.setStyleSheet(style)
        for callback in getattr(widget, '_folego_theme_callbacks', ()):
            callback()
        widget.update()


def choose_theme(theme_id, *, store=None):
    if theme_id not in THEMES: raise ValueError('Tema desconhecido')
    store = store if store is not None else QSettings('folego', 'folego')
    store.setValue(THEME_KEY, theme_id)
    store.sync()
    if store.status() != QSettings.Status.NoError:
        raise RuntimeError('Tema não foi salvo; confira as permissões da configuração')
    app = QApplication.instance()
    if app is not None: app.setProperty('folego_theme_error', '')
    apply_theme(app, theme_id)


def choose_transparency(value, *, store=None):
    if type(value) is not int: raise ValueError('Transparência deve ser um inteiro de 0 a 100%.')
    value = _transparency(value)
    store = store if store is not None else QSettings('folego', 'folego')
    store.setValue(TRANSPARENCY_KEY, value)
    store.sync()
    if store.status() != QSettings.Status.NoError:
        raise RuntimeError('Transparência não foi salva; confira as permissões da configuração')
    app = QApplication.instance()
    if app is not None: app.setProperty('folego_theme_error', '')
    apply_theme(app, TOKENS.key, transparency=value)
