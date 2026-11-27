"""A single keyboard-accessible profile picker for every Deck control surface."""
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                              QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..actions.deck_mapping import DeckMapping, PROFILES
from .deck_map_data import SECTIONS
from .desktop_shortcuts import DesktopController
from .theme import TOKENS, themed_style

ICONS = Path(__file__).parent / 'icons'


class DeckPicker(QFrame):
    def __init__(self, anchor, area, controller):
        super().__init__(anchor, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('Controle do Steam Deck')
        self.setAccessibleName(self.windowTitle())
        self.setObjectName('deckPicker')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        themed_style(self, lambda: f"""
            QFrame#deckPicker {{background-color:{TOKENS.surface};color:{TOKENS.text};
                border:1px solid {TOKENS.border};border-radius:8px;}}
            #deckPicker QWidget#deckPage, #deckPicker QScrollArea, #deckPicker QWidget#qt_scrollarea_viewport
                {{background-color:{TOKENS.background};border:0;}}
            #deckPicker QLabel {{color:{TOKENS.text};font-size:10pt;background:transparent;padding:2px;}}
            #deckPicker QLabel#deckGroup {{color:{TOKENS.text};font-weight:700;
                border-bottom:1px solid {TOKENS.border};padding:6px 0;}}
            #deckPicker QLabel#deckSaved {{color:{TOKENS.text};font-weight:600;}}
            #deckPicker QLabel#deckAlternate {{background-color:{TOKENS.surface_alt};}}
            #deckPicker QPushButton {{color:{TOKENS.text};background-color:{TOKENS.surface_alt};
                border:1px solid {TOKENS.border};border-radius:5px;padding:6px;text-align:left;}}
            #deckPicker QPushButton:checked, #deckPicker QPushButton:focus
                {{border:2px solid {TOKENS.focus};padding:5px;}}
            #deckPicker QPushButton#deckApply {{background-color:{TOKENS.accent};
                color:{TOKENS.accent_text};font-weight:700;text-align:center;}}
            #deckPicker QPushButton:disabled {{color:{TOKENS.muted};}}
        """)
        self.controller = controller
        self.choice = None
        self.preview = None
        outer = QGridLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        self.narrow = area.width() < 630
        menu = QWidget()
        controls = QVBoxLayout(menu)
        controls.setContentsMargins(3, 4, 5, 4)
        controls.addWidget(QLabel('<b>Controle do Steam Deck</b>'))
        self.options = {}
        for key, name in PROFILES.items():
            button = QPushButton(name + (' · padrão' if key == 'steam' else ' · KDE'))
            button.setAccessibleName('Prévia de ' + name)
            button.setCheckable(True)
            button.installEventFilter(self)
            button.clicked.connect(lambda _, k=key: self.show_preview(k))
            controls.addWidget(button)
            self.options[key] = button
        self.apply = QPushButton('Usar este perfil')
        self.apply.setObjectName('deckApply')
        self.apply.clicked.connect(self.save)
        controls.addWidget(self.apply)
        self.saved = QLabel('Lendo preferência…')
        self.saved.setObjectName('deckSaved')
        self.detail = QLabel()
        for label in (self.saved, self.detail):
            label.setWordWrap(True)
            controls.addWidget(label)
        self.games = QPushButton('Jogos reconhecidos')
        self.games.clicked.connect(lambda: controller.request('catalog'))
        controls.addWidget(self.games)
        controls.addStretch()
        outer.addWidget(menu, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumSize(1, 1)
        outer.addWidget(self.scroll, int(self.narrow), int(not self.narrow))
        if self.narrow:
            outer.setRowStretch(1, 1)
        else:
            menu.setFixedWidth(min(212, area.width() // 3))
            outer.setColumnStretch(1, 1)
        self.resize(min(910, area.width()-8), min(625, area.height()-8))
        controller.payload.connect(self.loaded)
        controller.failed.connect(self.error)
        controller.busy_changed.connect(self.busy)
        self.touched = False
        self.show_preview('steam', user=False)
        self.apply.setEnabled(False)

    def paintEvent(self, event):
        # A popup parented to the translucent mini bar needs its own opaque surface.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(TOKENS.surface))
        painter.end()
        super().paintEvent(event)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Enter, QEvent.Type.FocusIn):
            for key, button in self.options.items():
                if obj is button:
                    self.show_preview(key)
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.focusWidget() in self.options.values():
            self.options['phasezero' if self.preview == 'steam' else 'steam'].setFocus()
        else:
            super().keyPressEvent(event)

    def show_preview(self, key, *, user=True):
        if user:
            self.touched = True
        for name, button in self.options.items():
            button.setChecked(name == key)
        if key == self.preview:
            return
        self.preview = key
        page = QWidget()
        page.setObjectName('deckPage')
        page.setAccessibleName('Mapa de atalhos ' + PROFILES[key])
        layout = QVBoxLayout(page)
        title = QLabel('<h2>' + PROFILES[key] + '</h2>')
        banner = QHBoxLayout()
        banner.addWidget(title, 1)
        layout.addLayout(banner)
        deck = QSvgWidget(str(ICONS / 'deck-console.svg'))
        deck.setAccessibleName('Vista frontal. Botão Steam sob o trackpad esquerdo e três pontos sob o direito.')
        deck.setFixedSize(min(305, self.width() // 2), min(116, self.width() // 5))
        banner.addWidget(deck)
        for group, rows in SECTIONS:
            heading = QLabel(group)
            heading.setObjectName('deckGroup')
            layout.addWidget(heading)
            grid = QGridLayout()
            grid.setColumnStretch(0, 5)
            grid.setColumnStretch(1, 7)
            for row, (control, steam, phasezero) in enumerate(rows):
                action = steam if key == 'steam' else phasezero
                if action == '—':
                    continue
                for column, value in enumerate((control, action)):
                    label = QLabel(value)
                    if row % 2 == 0:
                        label.setObjectName('deckAlternate')
                    label.setWordWrap(True)
                    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                    grid.addWidget(label, row, column)
            layout.addLayout(grid)
            layout.addSpacing(8)
        if key == 'steam':
            note = QLabel('¹ A disponibilidade depende do cliente, da gravação e do sistema.')
            note.setWordWrap(True)
            layout.addWidget(note)
        self.scroll.setWidget(page)
        self.scroll.verticalScrollBar().setValue(0)
        self.apply.setText('Usar ' + PROFILES[key])
        self.apply.setEnabled(self.choice is not None and self.controller.future is None)

    def loaded(self, result):
        if 'emulators' in result:
            self.preview = None
            for button in self.options.values():
                button.setChecked(False)
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.addWidget(QLabel('<h2>Contexto de jogo</h2>'))
            for name, items in (('Front-ends', result['frontends']), ('Emuladores', result['emulators']),
                                ('Adicionados neste host', result['additional'])):
                if items:
                    layout.addWidget(QLabel('<b>' + name + '</b>'))
                    line = QLabel(' · '.join(items))
                    line.setWordWrap(True)
                    layout.addWidget(line)
            note = QLabel('Jogos com ID do Steam e programas iniciados por accessibility lease-run '
                          'também reservam o controle. Use accessibility deck-games --add para '
                          'registrar outro executável ou ID Flatpak.')
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch()
            self.scroll.setWidget(page)
            return
        self.choice = result['choice']
        self.saved.setText('Preferência salva · ' + PROFILES[self.choice])
        self.detail.setText(result['message'])
        if not self.touched:
            self.show_preview(self.choice, user=False)

    def busy(self, value):
        self.apply.setEnabled(not value and self.choice is not None and self.preview is not None)
        self.games.setEnabled(not value)

    def error(self, message):
        self.detail.setText(message)

    def save(self):
        self.controller.request('select', self.preview)


class DeckButton(QToolButton):
    def __init__(self, parent=None, *, backend=None):
        super().__init__(parent)
        self.setAccessibleName('Perfis de controle do Steam Deck')
        self.setIcon(QIcon(str(ICONS / 'deck-control.svg')))
        self.setIconSize(QSize(23, 23))
        self.setFixedSize(28, 28)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoRaise(True)
        self.controller = DesktopController(self, backend=backend or DeckMapping())
        self.picker = None
        self.hover = QTimer(self)
        self.hover.setSingleShot(True)
        self.hover.setInterval(320)
        self.hover.timeout.connect(self.open_picker)
        self.clicked.connect(self.open_picker)

    def enterEvent(self, event):
        super().enterEvent(event)
        if self.picker is None:
            self.hover.start()

    def leaveEvent(self, event):
        self.hover.stop()
        super().leaveEvent(event)

    def open_picker(self):
        self.hover.stop()
        if self.picker is not None or not self.isVisible():
            return
        area = self.screen().availableGeometry()
        picker = DeckPicker(self, area, self.controller)
        self.picker = picker
        picker.destroyed.connect(self._closed)
        anchor = self.mapToGlobal(QPoint(0, 0))
        x = min(max(area.left(), anchor.x()), area.right() - picker.width() + 1)
        below = anchor.y() + self.height()
        y = below if below + picker.height() <= area.bottom()+1 else max(area.top(), anchor.y()-picker.height())
        picker.move(x, y)
        picker.setFocus()
        picker.show()
        if self.controller.future is None:
            self.controller.request('status')

    def _closed(self):
        self.picker = None
