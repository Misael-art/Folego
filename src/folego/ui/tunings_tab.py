"""M3 tunings tab: one row per adjustment, every verdict from the child.

Nothing here opens the browser's config: the row asks the worker and prints what
comes back, in the same words the CLI uses. Buttons stay disabled until a verdict
arrives, a click always confirms, and a refusal is written in the row instead of
disappearing — a silent "nothing happened" would look like success.
"""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QGridLayout, QGroupBox, QLabel, QMessageBox,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..actions.tunings.registry import TUNINGS

PENDING = "consultando…"


class TuningRow(QGroupBox):
    def __init__(self, tuning, parent=None):
        super().__init__(tuning.label, parent)
        self.tuning = tuning
        self.file_label = QLabel("")
        self.file_label.setWordWrap(True)
        self.file_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                      QSizePolicy.Policy.Preferred)
        self.state_label = QLabel(PENDING)
        self.state_label.setWordWrap(True)
        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        why = QLabel(tuning.why)
        why.setWordWrap(True)
        why.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.apply_button = QPushButton("Aplicar")
        self.revert_button = QPushButton("Reverter")
        for button in (self.apply_button, self.revert_button):
            button.setEnabled(False)

        grid = QGridLayout()
        grid.addWidget(QLabel("estado:"), 0, 0)
        grid.addWidget(self.state_label, 0, 1)
        grid.addWidget(QLabel("arquivo:"), 1, 0)
        grid.addWidget(self.file_label, 1, 1)
        grid.addWidget(QLabel("motivo:"), 2, 0)
        grid.addWidget(why, 2, 1)
        grid.setColumnStretch(1, 1)

        buttons = QVBoxLayout()
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.revert_button)
        outer = QGridLayout()
        outer.addLayout(grid, 0, 0)
        outer.addLayout(buttons, 0, 1)
        outer.setColumnStretch(0, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(outer)
        layout.addWidget(self.verdict)


class TuningsTab(QWidget):
    def __init__(self, *, jobs, confirm_fn=None, tunings=None, parent=None):
        super().__init__(parent)
        self._jobs = jobs
        self._confirm = confirm_fn or self._ask_dialog
        self._tunings = tuple(tunings if tunings is not None else TUNINGS)
        self._applied: set[str] = set()
        self._uncertain: set[str] = set()
        self._pending_ids = {}

        layout = QVBoxLayout(self)
        self.rows: list[TuningRow] = []
        for tuning in self._tunings:
            row = TuningRow(tuning)
            row.apply_button.clicked.connect(
                lambda _=False, t=tuning: self.apply_clicked(t))
            row.revert_button.clicked.connect(
                lambda _=False, t=tuning: self.revert_clicked(t))
            self.rows.append(row)
            layout.addWidget(row)
        self.reload_button = QPushButton("Reconsultar o navegador")
        self.reload_button.clicked.connect(self.refresh)
        layout.addWidget(self.reload_button)
        layout.addStretch(1)

    # ------------------------------------------------------------------ reading

    def refresh(self):
        for row in self.rows:
            row.state_label.setText(PENDING)
            row.apply_button.setEnabled(False)
            row.revert_button.setEnabled(False)
        for tuning in self._tunings:
            self._jobs.run("detect", tuning.id,
                           done=lambda payload, t=tuning: self.show_detect(t, payload))

    def row_for(self, tuning_id: str) -> TuningRow:
        return next(r for r in self.rows if r.tuning.id == tuning_id)

    def show_detect(self, tuning, payload):
        row = self.row_for(tuning.id)
        if payload is None:
            row.state_label.setText("o filho não respondeu")
            return
        row.file_label.setText(str(payload.get("file") or "—"))
        if payload.get("error"):
            row.state_label.setText(payload["error"])
            if tuning.id not in self._uncertain:
                row.verdict.setText("")
            return
        if not payload.get("exists"):
            row.state_label.setText("arquivo não existe")
            return

        if payload.get("change_needed"):
            if tuning.id in self._applied:
                row.state_label.setText("sobrescrito — reaplicar: o Edge regravou "
                                        "este arquivo")
            else:
                row.state_label.setText("ligado" if payload.get("current")
                                        else "fora do valor desejado")
            row.apply_button.setEnabled(True)
        else:
            row.state_label.setText("desligado (já econômico)")
        row.revert_button.setEnabled(True)
        if self._uncertain:
            row.apply_button.setEnabled(False)
            row.revert_button.setEnabled(False)

    # -------------------------------------------------------------------- acts

    def apply_clicked(self, tuning):
        if self._uncertain:
            return
        row = self.row_for(tuning.id)
        self._jobs.review_and_run("apply", tuning.id, title="Aplicar ajuste", confirm_fn=self._confirm,
                expected_scope=[{"key": row.file_label.text()}],
                text=
                f"Vou escrever em {row.file_label.text() or 'arquivo do navegador'}.\n\n"
                "O Microsoft Edge precisa estar fechado: ao sair ele regrava este "
                "arquivo e desfaz o ajuste.\n"
                "Uma cópia do arquivo atual fica em backup e pode ser revertida.",
                       done=lambda payload: self.show_mutation("aplicado", tuning,
                                                               payload))

    def revert_clicked(self, tuning):
        if self._uncertain:
            return
        row = self.row_for(tuning.id)
        self._jobs.review_and_run("revert", tuning.id, title="Reverter ajuste", confirm_fn=self._confirm,
                expected_scope=[{"key": row.file_label.text()}],
                text=
                "Vou devolver este arquivo ao último backup feito pelo Fôlego. "
                "Alterações feitas depois disso pelo próprio Edge seriam descartadas.",
                       done=lambda payload: self.show_mutation("restaurado", tuning,
                                                               payload))

    def show_mutation(self, success_word: str, tuning, payload):
        row = self.row_for(tuning.id)
        if payload and payload.get("outcome") == "cancelamento":
            row.verdict.setText(payload.get("reason", "cancelado: nenhum efeito solicitado"))
            return
        if not payload or payload.get("outcome") == "desconhecido":
            self._uncertain.add(tuning.id)
            self._pending_ids[tuning.id] = (payload or {}).get("operation_id")
            payload = payload or {}
            for other in self.rows:
                other.apply_button.setEnabled(False)
                other.revert_button.setEnabled(False)
            row.verdict.setText("desconhecido: " + str(payload.get("reason") or "o filho não respondeu") +
                " · operação " + str(payload.get("operation_id") or "consulte o histórico") +
                " · não repetir antes de reconciliar")
            return
        if not payload.get("ok") or payload.get("outcome") in ("parcial", "falha", "recusa"):
            label = {"parcial": "parcial", "falha": "falha"}.get(payload.get("outcome"), "recusado")
            row.verdict.setText(f"{label}: {payload.get('reason') or 'motivo não informado'}" +
                (f" · operação {payload['operation_id']}" if payload.get("operation_id") else ""))
            return
        if payload.get("acao") == "apply" and not payload.get("changed", True):
            row.verdict.setText(payload.get("reason") or "nada a fazer")
            return
        if payload.get("acao") == "apply":
            self._applied.add(tuning.id)
        parts = [success_word + ": " + tuning.label]
        if payload.get("sha"):
            parts.append(f"sha256 {payload['sha']}")
        if payload.get("backup_id"):
            parts.append(f"backup {payload['backup_id']}")
        row.verdict.setText(" · ".join(parts))
        QTimer.singleShot(0, self.refresh)

    def resolve_operation(self, payload):
        key = payload.get("operation_id")
        resolved = [tuning for tuning, operation in self._pending_ids.items() if key and operation == key]
        for tuning in resolved:
            self._uncertain.discard(tuning)
            self._pending_ids.pop(tuning, None)
            self.row_for(tuning).verdict.setText("verificado: " + str(payload.get("reason") or "resultado consultado"))
        if resolved: QTimer.singleShot(0, self.refresh)

    def _ask_dialog(self, title: str, text: str) -> bool:
        from .confirmation import confirm_text
        return confirm_text(title, text, self)
