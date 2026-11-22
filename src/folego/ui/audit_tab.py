"""The local audit timeline, with an off-thread reader."""
import json
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QHeaderView, QVBoxLayout, QWidget)

from ..adapters.host_audit import LABELS, history
from .workers import Poller

KINDS = {
    "sample": "Amostra", "incident": "Incidente", "baseline": "Primeira leitura",
    "added": "Adicionado", "removed": "Removido", "changed": "Alterado", "source": "Cobertura da fonte",
}


class AuditTab(QWidget):
    def __init__(self):
        super().__init__()
        self._before = None
        self._selection = (None, None)
        self._events = []
        self._poller = None
        layout = QVBoxLayout(self)
        self.profile = QLabel()
        self.profile.setWordWrap(True)
        self.profile.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.profile)
        filters = QHBoxLayout()
        self.source = QComboBox()
        self.source.setAccessibleName("Filtrar linha do tempo por fonte")
        self.source.addItem("Mudanças, falhas e avisos", "changes")
        self.source.addItem("Tudo", None)
        for key, label in LABELS.items():
            self.source.addItem(label, key)
        self.source.currentIndexChanged.connect(self.latest)
        filters.addWidget(self.source, 1)
        self.latest_button = QPushButton("Mais recentes")
        self.latest_button.clicked.connect(self.latest)
        filters.addWidget(self.latest_button)
        self.older = QPushButton("Anteriores")
        self.older.setEnabled(False)
        self.older.clicked.connect(self.previous)
        filters.addWidget(self.older)
        layout.addLayout(filters)
        self.coverage = QLabel("Aguardando leitura do histórico.")
        self.coverage.setWordWrap(True)
        self.coverage.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.coverage)
        self.table = QTableWidget(0, 4)
        self.table.setAccessibleName("Linha do tempo do host")
        self.table.setHorizontalHeaderLabels(("Data e hora", "Fonte", "Evento", "Item"))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.currentCellChanged.connect(self.show_detail)
        layout.addWidget(self.table, 3)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Detalhes do registro")
        self.details.setPlaceholderText("Selecione um registro para consultar a evidência.")
        layout.addWidget(self.details, 2)
        self._record_error = ""
        self._history_note = ""

    def show_profile(self, value):
        enabled = value["enabled"]
        self.profile.setText("Modo Auditor ativo" if enabled is True else
                             "Modo Auditor desativado. Ative em Opções." if enabled is False else
                             "Preferência do Modo Auditor ilegível. Automações suspensas.")
        if enabled is not True:
            self.show_record_error("")

    def show_record_error(self, message):
        self._record_error = message
        self.coverage.setText(" · ".join(filter(None, (message, self._history_note))))

    def latest(self, *_):
        self._before = None
        self.refresh()

    def previous(self):
        if self._events:
            self._before = self._events[-1]["id"]
            self.refresh()

    def refresh(self):
        self._selection = self.source.currentData(), self._before
        self.older.setEnabled(False)
        if self._poller is not None:
            self._poller.request()

    def _read(self):
        selected, before = self._selection
        report = history(source=None if selected == "changes" else selected, changes_only=selected == "changes",
                         before_id=before, limit=100)
        return (selected, before), report

    def _show_history(self, result):
        selection, report = result
        if selection != self._selection:
            self.refresh()
            return
        gaps = [LABELS[name] for name, state in report["sources"].items() if state["quality"] != "ok"]
        fresh = [state["checked"] for state in report["sources"].values()]
        count = len(report["events"])
        note = report.get("reason") or (f"{count} registros nesta página" if count else "Sem registros neste filtro.")
        if gaps:
            note += " · Cobertura parcial: " + ", ".join(gaps)
        if fresh:
            note += " · Última verificação: " + max(fresh)[:19].replace("T", " ")
        self._history_note = note
        self.show_record_error(self._record_error)
        old_row = self.table.currentRow()
        selected_id = self._events[old_row]["id"] if 0 <= old_row < len(self._events) else None
        self._events = list(reversed(report["events"]))
        self.older.setEnabled(report.get("limited", False))
        self.table.setRowCount(len(self._events))
        new_row = -1
        for index, event in enumerate(self._events):
            date = datetime.fromisoformat(event["at"]).astimezone().strftime("%d/%m/%Y %H:%M:%S")
            values = date, LABELS[event["source"]], KINDS[event["kind"]], event["subject"].replace("\n", " ")
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(value))
            if event["id"] == selected_id:
                new_row = index
        self.table.setCurrentCell(new_row, 0)
        self.show_detail(new_row)

    def show_detail(self, row, *_):
        if 0 <= row < len(self._events):
            event = self._events[row]
            evidence = json.dumps(event["data"], ensure_ascii=False, indent=2)
            self.details.setPlainText(f"Registro {event['id']} · Boot {event['boot_id']}\n{evidence}")
        else:
            self.details.clear()

    def showEvent(self, event):
        super().showEvent(event)
        if self._poller is None:
            self._poller = Poller(self._read, interval_s=15, parent=self, offload=True)
            self._poller.snapshot_ready.connect(self._show_history)
            self._poller.error.connect(self.show_record_error)
        self._poller.resume()

    def hideEvent(self, event):
        if self._poller is not None:
            self._poller.pause()
        super().hideEvent(event)

    def stop(self):
        if self._poller is not None:
            self._poller.stop()
