"""Design tokens for the manual central: one palette, one focus ring, no motion.

The app is a diagnostic bench, not a dashboard for a wall display. Tokens keep
the same severity colours across tabs, but colour is never the only signal: the
text says "crítico", "parcial" or "recusado" as well. Qt scales fonts with the
desktop DPI; sizes here are relative and spacing is in logical pixels. There is
no animation, so ``prefers-reduced-motion`` has nothing to disable.
"""
from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Tokens:
    background: str = "#0f1419"
    surface: str = "#171e26"
    surface_alt: str = "#1e2731"
    text: str = "#f2f5f7"
    muted: str = "#b3bec8"
    accent: str = "#63b3ff"
    accent_text: str = "#08121c"
    ok: str = "#5dd39e"
    warning: str = "#ffc266"
    danger: str = "#ff7b7b"
    focus: str = "#ffd166"
    border: str = "#33414f"
    spacing: int = 8
    radius: int = 6


TOKENS = Tokens()

STYLESHEET = f"""
QWidget {{
    background-color: {TOKENS.background};
    color: {TOKENS.text};
    selection-background-color: {TOKENS.accent};
    selection-color: {TOKENS.accent_text};
}}
QMainWindow, QTabWidget::pane, QScrollArea {{
    background-color: {TOKENS.background};
}}
QTabWidget::pane {{
    border: 1px solid {TOKENS.border};
    border-radius: {TOKENS.radius}px;
    top: -1px;
}}
QTabBar::tab {{
    background: {TOKENS.surface};
    color: {TOKENS.muted};
    padding: 7px 14px;
    margin-right: 2px;
    border: 1px solid {TOKENS.border};
    border-bottom: none;
    border-top-left-radius: {TOKENS.radius}px;
    border-top-right-radius: {TOKENS.radius}px;
}}
QTabBar::tab:selected {{
    background: {TOKENS.surface_alt};
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
    padding: 12px 16px;
    margin: 2px 6px 2px 0;
    border: none;
    border-left: 3px solid transparent;
    border-radius: {TOKENS.radius}px;
    text-align: left;
}}
QTabWidget#sidebar QTabBar::tab:selected {{
    background: {TOKENS.surface_alt};
    color: {TOKENS.text};
    border-left: 3px solid {TOKENS.accent};
}}
QTabWidget#sidebar QTabBar::tab:focus {{
    border: 2px solid {TOKENS.focus};
}}
QFrame#hero, QFrame#card {{
    background: {TOKENS.surface};
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
QPushButton#primary {{
    background: {TOKENS.accent};
    color: {TOKENS.accent_text};
    border: 1px solid {TOKENS.accent};
    font-weight: 600;
    padding: 9px 18px;
}}
QPushButton#primary:disabled {{
    background: {TOKENS.surface_alt};
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
    background: {TOKENS.surface_alt};
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
    background: {TOKENS.surface};
}}
QPushButton:default {{
    border-color: {TOKENS.accent};
}}
QTableWidget, QTreeWidget, QListView {{
    background: {TOKENS.surface};
    alternate-background-color: {TOKENS.surface_alt};
    gridline-color: {TOKENS.border};
    border: 1px solid {TOKENS.border};
    border-radius: {TOKENS.radius}px;
}}
QHeaderView::section {{
    background: {TOKENS.surface_alt};
    color: {TOKENS.muted};
    border: none;
    border-bottom: 1px solid {TOKENS.border};
    padding: 4px 6px;
}}
QTableWidget:focus, QTreeWidget:focus {{
    border: 2px solid {TOKENS.focus};
}}
QProgressBar {{
    background: {TOKENS.surface_alt};
    border: 1px solid {TOKENS.border};
    border-radius: {TOKENS.radius}px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {TOKENS.accent};
    border-radius: {TOKENS.radius - 1}px;
}}
QToolTip {{
    background: {TOKENS.surface_alt};
    color: {TOKENS.text};
    border: 1px solid {TOKENS.focus};
    padding: 4px;
}}
"""


def apply_theme(app: QApplication | None = None) -> None:
    app = app or QApplication.instance()
    if app is None:
        return
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(TOKENS.background))
    palette.setColor(QPalette.ColorRole.Base, QColor(TOKENS.surface))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(TOKENS.surface_alt))
    palette.setColor(QPalette.ColorRole.Text, QColor(TOKENS.text))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TOKENS.text))
    palette.setColor(QPalette.ColorRole.Button, QColor(TOKENS.surface_alt))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TOKENS.text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(TOKENS.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TOKENS.accent_text))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
