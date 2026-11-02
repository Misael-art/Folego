"""Grouped prompt picker. Presentation/signals only; no storage or native I/O."""
from pathlib import Path
from PySide6.QtCore import Qt, QEvent, QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
                              QHBoxLayout, QScrollArea, QStyle, QSizePolicy,
                              QApplication)

from ..core.development_prompts import PROMPTS, PROMPT_CATEGORIES
from .theme import themed_style, TOKENS as T, control_icon, tint_icon, on_theme_change


class PickerButton(QPushButton):
    """Full-row native button with wrapping text and trailing theme icon."""
    def __init__(self, title, icon, parent=None):
        super().__init__(parent)
        self.setObjectName('promptChoice')
        self.setAccessibleName(title)
        self.setToolTip(title)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        themed_style(self, lambda: f'QPushButton#promptChoice{{background:transparent;color:{T.text};'
                           'min-height:0;padding:0;border:1px solid transparent;border-radius:5px;}'
                           f'QPushButton#promptChoice:hover{{background:{T.surface_alt};border-color:{T.accent};}}'
                           f'QPushButton#promptChoice:focus{{background:{T.surface_alt};border-color:{T.focus};}}')
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(8)
        self.label = QLabel(title)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setStyleSheet('background:transparent;border:none;font-size:10pt;')
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self.label, 1)
        image = QLabel()
        image.setStyleSheet('background:transparent;border:none;')
        image.setPixmap(icon.pixmap(14, 14))
        on_theme_change(image, lambda: image.setPixmap(tint_icon(icon).pixmap(14, 14)))
        image.setFixedSize(14, 14)
        image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(image)

    def sizeHint(self):
        return self.layout().sizeHint().expandedTo(QSize(0, 24))

    def minimumSizeHint(self):
        return QSize(0, 24)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return max(24, self.label.heightForWidth(max(1, width - 34)) + 6)


class PromptPanel(QWidget):
    prompt_selected = Signal(str)
    footer_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('promptPanel')
        self.setAccessibleName('Prompts por categoria')
        themed_style(self, lambda: f'QWidget{{background:{T.surface};color:{T.text};}}'
                          'QWidget#promptPanel{border-radius:7px;}')
        self.buttons = {}
        self.headings = {}
        self.footer_buttons = {}
        self.footer_menus = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QWidget()
        header.setStyleSheet('background:transparent;')
        top = QVBoxLayout(header)
        top.setContentsMargins(16, 8, 16, 6)
        top.setSpacing(2)
        line = QHBoxLayout()
        title = QLabel('Prompts')
        title.setStyleSheet('font-size:15pt;font-weight:700;')
        self.count = QLabel(f'{len(PROMPTS)} modelos')
        themed_style(self.count, lambda: f'font-size:10pt;color:{T.muted};')
        line.addWidget(title, 1)
        line.addWidget(self.count)
        top.addLayout(line)
        hint = QLabel('Clique em um título para copiar')
        themed_style(hint, lambda: f'font-size:10pt;color:{T.muted};')
        top.addWidget(hint)
        outer.addWidget(header)
        outer.addWidget(self.separator())
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        themed_style(self.scroll, lambda: f'QScrollArea,QScrollArea>QWidget>QWidget{{background:{T.surface};}}'
            f'QScrollBar:vertical{{background:{T.surface_alt};width:6px;margin:2px 0;}}'
            f'QScrollBar::handle:vertical{{background:{T.border};min-height:24px;border-radius:3px;}}'
            'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}'
            'QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}')
        content = QWidget()
        blocks = QVBoxLayout(content)
        blocks.setContentsMargins(12, 8, 10, 8)
        blocks.setSpacing(4)
        prompts = {p.key: p for p in PROMPTS}
        icons = Path(__file__).with_name('icons')
        copy_icon = control_icon(self.style(), 'edit-copy', QStyle.StandardPixmap.SP_FileIcon,
                                 fallback_icon=QIcon(str(icons / 'copy.svg')))
        for index, (key, title, identities) in enumerate(PROMPT_CATEGORIES):
            if index: blocks.addWidget(self.separator())
            group = QWidget()
            group.setAccessibleName(title)
            row = QHBoxLayout(group)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            stripe = QFrame()
            stripe.setObjectName('promptStripe_' + key)
            stripe.setFixedWidth(3)
            themed_style(stripe, lambda slot=index: f'background:{T.categories[slot]};border-radius:1px;min-width:3px;max-width:3px;')
            row.addWidget(stripe)
            column = QVBoxLayout()
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(0)
            heading = QLabel(title)
            heading.setWordWrap(True)
            heading.setStyleSheet('background:transparent;font-size:10pt;font-weight:700;padding:1px 6px;')
            column.addWidget(heading)
            self.headings[key] = heading
            for identity in identities:
                prompt = prompts[identity]
                button = PickerButton(prompt.title, copy_icon)
                button.setAccessibleDescription('Copiar prompt · ' + title)
                button.clicked.connect(lambda checked=False, key=identity: self.prompt_selected.emit(key))
                button.installEventFilter(self)
                column.addWidget(button)
                self.buttons[identity] = button
            row.addLayout(column, 1)
            blocks.addWidget(group)
        blocks.addStretch()
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll, 1)
        outer.addWidget(self.separator())
        footer = QWidget()
        footer.setStyleSheet('background:transparent;')
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(6, 5, 6, 5)
        bottom.setSpacing(2)
        arrow = control_icon(self.style(), 'go-next', QStyle.StandardPixmap.SP_ArrowRight,
                             fallback_icon=QIcon(str(icons / 'chevron-right.svg')))
        for name in ('Janelas', 'Edição', 'Terminal', 'Custom'):
            button = PickerButton(name, arrow)
            button.layout().setContentsMargins(4, 3, 4, 3)
            button.layout().setSpacing(4)
            button.setAccessibleDescription('Abrir ' + name)
            button.clicked.connect(lambda checked=False, key=name: self.footer_requested.emit(key))
            button.installEventFilter(self)
            bottom.addWidget(button, 1)
            self.footer_buttons[name] = button
        outer.addWidget(footer)
        if parent: parent.installEventFilter(self)

    @staticmethod
    def separator():
        line = QFrame()
        line.setFixedHeight(1)
        themed_style(line, lambda: f'background:{T.border};border:none;min-height:1px;max-height:1px;')
        return line

    def sizeHint(self):
        # QWidgetAction consults this after stylesheet polishing, which may
        # reset minimumHeight; the screen-specific maximum still bounds it.
        return QSize(478, 538)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusIn and watched in self.buttons.values():
            self.scroll.ensureWidgetVisible(watched, 0, 8)
        if event.type() == QEvent.Type.KeyPress:
            order = list(self.buttons.values()) + list(self.footer_buttons.values())
            focused = QApplication.focusWidget()
            index = order.index(focused) if focused in order else -1
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
                       Qt.Key.Key_Home, Qt.Key.Key_End):
                if key == Qt.Key.Key_Home: index = 0
                elif key == Qt.Key.Key_End: index = len(order) - 1
                else: index = (index + (-1 if key in (Qt.Key.Key_Up, Qt.Key.Key_Backtab) else 1)) % len(order)
                order[index].setFocus(Qt.FocusReason.TabFocusReason)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and index >= 0:
                focused.click()
                return True
        return super().eventFilter(watched, event)
