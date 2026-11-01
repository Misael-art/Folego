"""Lazy editor for the compact menu's private texts and keyboard macros."""
import uuid

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
                              QPushButton, QLineEdit, QPlainTextEdit, QComboBox,
                              QStackedWidget, QMessageBox)

from .desktop_shortcuts import DesktopController


class CustomPromptsTab(QWidget):
    def __init__(self, parent=None, *, controller=None):
        super().__init__(parent)
        self.controller = controller
        self.initialized = False
        self.entries = []
        self.revision = None
        self.current_key = None
        self.current_kind = 'text'
        self.dirty = False
        self.readable = False
        self.busy = False
        self._selection_after_save = None

    def showEvent(self, event):
        super().showEvent(event)
        if not self.initialized:
            self._build()
            self.reload()

    def _build(self):
        self.initialized = True
        self.controller = self.controller or DesktopController(self)
        self.controller.payload.connect(self._loaded)
        self.controller.feedback.connect(self._feedback)
        self.controller.failed.connect(self._failed)
        self.controller.busy_changed.connect(self._busy_changed)
        layout = QVBoxLayout(self)
        heading = QLabel('Textos e macros personalizados')
        heading.setObjectName('section')
        layout.addWidget(heading)
        intro = QLabel('Os itens aparecem em Prompts → Custom no modo compacto. '
                       'Textos são copiados; macros executam somente o atalho escolhido.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        body = QHBoxLayout()
        self.items = QListWidget()
        self.items.setAccessibleName('Textos e macros cadastrados')
        self.items.setMinimumWidth(155)
        self.items.setMaximumWidth(220)
        self.items.currentRowChanged.connect(self._selected)
        body.addWidget(self.items, 1)
        self.form = QWidget()
        fields = QVBoxLayout(self.form)
        fields.setContentsMargins(0, 0, 0, 0)
        self.kind_label = QLabel('Texto')
        fields.addWidget(self.kind_label)
        self.title = QLineEdit()
        self.title.setMaxLength(80)
        self.title.setPlaceholderText('Título que aparece no menu')
        self.title.setAccessibleName('Título do item personalizado')
        self.title.textChanged.connect(self._changed)
        fields.addWidget(self.title)
        self.details = QStackedWidget()
        self.text = QPlainTextEdit()
        self.text.setAccessibleName('Texto personalizado para copiar')
        self.text.setPlaceholderText('Digite o texto que deseja copiar pelo menu Custom')
        self.text.setMinimumHeight(100)
        self.text.textChanged.connect(self._changed)
        self.details.addWidget(self.text)
        macro = QWidget()
        macro_layout = QVBoxLayout(macro)
        macro_layout.setContentsMargins(0, 0, 0, 0)
        self.action = QComboBox()
        self.action.addItem('Mostrar área de trabalho', 'desktop')
        self.action.addItem('Atalho de teclado personalizado', 'keys')
        self.action.setAccessibleName('Ação da macro')
        self.action.currentIndexChanged.connect(self._macro_changed)
        macro_layout.addWidget(self.action)
        self.shortcut = QLineEdit()
        self.shortcut.setAccessibleName('Atalho da macro')
        self.shortcut.setPlaceholderText('Ex.: Ctrl+Alt+T ou Meta+D')
        self.shortcut.textChanged.connect(self._changed)
        macro_layout.addWidget(self.shortcut)
        self.help = QLabel()
        self.help.setWordWrap(True)
        macro_layout.addWidget(self.help)
        macro_layout.addStretch()
        self.details.addWidget(macro)
        fields.addWidget(self.details, 1)
        body.addWidget(self.form, 3)
        layout.addLayout(body, 1)
        actions = QHBoxLayout()
        self.add_text = QPushButton('+ Texto')
        self.add_text.clicked.connect(lambda: self.new_item('text'))
        self.add_macro = QPushButton('+ Macro')
        self.add_macro.clicked.connect(lambda: self.new_item('macro'))
        self.save = QPushButton('Salvar')
        self.save.setObjectName('primary')
        self.save.clicked.connect(self.save_item)
        self.remove = QPushButton('Remover item')
        self.remove.clicked.connect(self.remove_item)
        self.refresh = QPushButton('Atualizar')
        self.refresh.clicked.connect(self.reload)
        for button in (self.add_text, self.add_macro, self.save, self.remove, self.refresh): actions.addWidget(button)
        layout.addLayout(actions)
        self.status = QLabel('Carregando personalizações…')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._sync_enabled()

    def _changed(self, *_):
        self.dirty = True

    def _macro_changed(self, *_):
        keys = self.action.currentData() == 'keys'
        self.shortcut.setVisible(keys)
        self.help.setText('Digite o atalho por extenso. Ele será enviado ao aplicativo em foco quando você escolher a macro.'
                          if keys else 'Mostra a área de trabalho sem fechar as aplicações. Requer KDE/KWin.')
        self._changed()

    def _discard(self):
        return not self.dirty or QMessageBox.question(self, 'Edição ainda não salva',
            'Descartar as alterações deste item?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _selected(self, row):
        if not 0 <= row < len(self.entries): return
        item = self.entries[row]
        if not self._discard():
            with QSignalBlocker(self.items):
                self.items.setCurrentRow(next((i for i, e in enumerate(self.entries) if e['id'] == self.current_key), -1))
            return
        self._fill(item)

    def _fill(self, item):
        self.current_key, self.current_kind = item.get('id'), item['kind']
        blockers = [QSignalBlocker(w) for w in (self.title, self.text, self.action, self.shortcut)]
        self.kind_label.setText('Texto para copiar' if item['kind'] == 'text' else 'Macro de atalho')
        self.title.setText(item.get('title', ''))
        self.text.setPlainText(item.get('text', ''))
        self.details.setCurrentIndex(0 if item['kind'] == 'text' else 1)
        self.action.setCurrentIndex(self.action.findData(item.get('action', 'desktop')))
        self.shortcut.setText(item.get('shortcut', ''))
        self._macro_changed()
        del blockers
        self.dirty = False
        self._sync_enabled()

    def new_item(self, kind):
        if not self._discard(): return
        with QSignalBlocker(self.items): self.items.setCurrentRow(-1)
        self._fill(dict(kind=kind, title='', text='', action='desktop'))
        self.dirty = True
        self.title.setFocus()

    def save_item(self):
        key = self.current_key or uuid.uuid4().hex
        item = dict(id=key, kind=self.current_kind, title=self.title.text())
        if self.current_kind == 'text': item['text'] = self.text.toPlainText()
        else:
            item['action'] = self.action.currentData()
            if item['action'] == 'keys': item['shortcut'] = self.shortcut.text()
        entries = [item if e['id'] == key else e for e in self.entries]
        if self.current_key is None: entries.append(item)
        self._selection_after_save = key
        self.controller.request('custom-save', dict(entries=entries, revision=self.revision))

    def remove_item(self):
        if self.current_key is None: return
        entries = [e for e in self.entries if e['id'] != self.current_key]
        self._selection_after_save = None
        self.controller.request('custom-save', dict(entries=entries, revision=self.revision))

    def reload(self):
        if self._discard(): self.controller.request('custom-load')

    def _loaded(self, payload):
        if payload.get('operation') not in ('custom-load', 'custom-save'): return
        self.entries, self.revision = payload['entries'], payload['revision']
        self.readable = True
        self.dirty = False
        with QSignalBlocker(self.items):
            self.items.clear()
            for item in self.entries:
                self.items.addItem(item['title'] + (' · Texto' if item['kind'] == 'text' else ' · Macro'))
            row = next((i for i, e in enumerate(self.entries) if e['id'] == self._selection_after_save), 0)
            self.items.setCurrentRow(row if self.entries else -1)
        if self.entries: self._fill(self.entries[row])
        else: self._fill(dict(kind='text', title='', text=''))
        self.status.setText('Personalizações salvas. Disponíveis em Prompts → Custom.' if payload['operation'] == 'custom-save'
                            else 'Escolha um item ou use + Texto / + Macro para cadastrar.')
        self._sync_enabled()

    def _feedback(self, message):
        self.status.setText(message)

    def _failed(self, message):
        if self.controller.action == 'custom-load':
            self.readable = False

    def _busy_changed(self, busy):
        self.busy = busy
        self._sync_enabled()

    def _sync_enabled(self):
        if not self.initialized: return
        enabled = self.readable and not self.busy
        for widget in (self.items, self.form, self.add_text, self.add_macro, self.save): widget.setEnabled(enabled)
        self.remove.setEnabled(enabled and self.current_key is not None)
        self.refresh.setEnabled(not self.busy)

    def shutdown(self):
        if self.controller is not None: self.controller.close()
