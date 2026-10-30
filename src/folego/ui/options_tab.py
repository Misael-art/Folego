"""Session startup preference; all system/file operations run in a worker."""
import sys
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QLabel, QPushButton, QVBoxLayout, QWidget
from .tune_jobs import TuneJobs


def options_argv(action, target, confirm):
    if action.startswith("jobs-"):
        argv = [sys.executable, "-m", "folego", "jobs", action.removeprefix("jobs-"), "--json"]
        if confirm: argv.append("--confirmar")
        return argv
    argv = [sys.executable, "-m", "folego", "startup", action.removeprefix("startup-"), "--json"]
    if confirm:
        argv.append("--confirmar")
    return argv


class OptionsTab(QWidget):
    operation_verified = Signal(object)
    def __init__(self, *, jobs=None):
        super().__init__()
        self._stopped = False
        self.jobs = jobs or TuneJobs(parent=self, argv_factory=options_argv, timeout_ms=30000)
        self.choice = QCheckBox("Iniciar Fôlego automaticamente com a sessão")
        self.choice.setChecked(True)
        self.choice.setAccessibleName("Iniciar automaticamente com a sessão, ligado por padrão")
        self.choice.clicked.connect(self.changed)
        self.status = QLabel("Ligado por padrão; aguardando verificação da configuração efetiva.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.verify = QPushButton("Verificar configuração")
        self.verify.clicked.connect(lambda: self.start())
        self.pending = QComboBox()
        self.pending.setAccessibleName("Operações com resultado pendente")
        self.operation_id = QLineEdit()
        self.operation_id.setPlaceholderText("Cole o código da operação para consultar sem repetir")
        self.operation_id.setAccessibleName("Código da operação a verificar")
        self.operation_id.textChanged.connect(lambda text: self.reconcile.setEnabled(bool(text or self.pending.currentData())))
        self.reconcile = QPushButton("Verificar operação pendente sem repetir")
        self.reconcile.clicked.connect(self.check_operation)
        self.cancel = QPushButton("Cancelar revisão ainda não iniciada")
        self.cancel.clicked.connect(self.cancel_review)
        self.operation_status = QLabel("Nenhuma recuperação solicitada.")
        self.operation_status.setWordWrap(True)
        self.operation_status.setTextFormat(Qt.TextFormat.PlainText)
        self.retention = QLabel("Temporários próprios: ainda não consultados.")
        self.retention.setWordWrap(True)
        self.retention.setTextFormat(Qt.TextFormat.PlainText)
        self.retain = QPushButton("Reter temporários concluídos preservando conteúdo")
        self.retain.clicked.connect(lambda: self.jobs.run("jobs-retain", "", confirm=True, done=self.retained))
        text = QLabel("A opção inicia a central e o monitor com seu login gráfico. "
                      "Não amplia permissões de reparo ou limpeza. Desligar afeta o próximo login; "
                      "o monitor já aberto pode continuar observando.")
        text.setWordWrap(True)
        box = QVBoxLayout(self)
        for widget in (self.choice, text, self.status, self.verify, self.pending, self.operation_id, self.reconcile, self.cancel, self.operation_status, self.retention, self.retain):
            box.addWidget(widget)
        box.addStretch(1)

    def start(self, *, sync=False):
        if self._stopped: return
        self.choice.setEnabled(False)
        self.jobs.run("startup-sync" if sync else "startup-status", "", done=self.done)
        self.jobs.run("review-pending", "", done=self.show_pending)
        self.jobs.run("jobs-status", "", done=self.show_retention)

    def show_pending(self, payload):
        if self._stopped: return
        self.pending.clear()
        rows = (payload or {}).get("pending")
        if not isinstance(rows, list):
            self.pending.addItem("Consulta de operações indisponível", None)
            self.reconcile.setEnabled(False)
            self.cancel.setEnabled(False)
            return
        for row in rows:
            self.pending.addItem(row["action"] + " · " + row["operation_id"], row["operation_id"])
        self.reconcile.setEnabled(bool(rows or self.operation_id.text().strip()))
        self.cancel.setEnabled(bool(rows))
        if not rows:
            self.pending.addItem("Nenhuma revisão/operação pendente", None)

    def check_operation(self):
        key = self.operation_id.text().strip() or self.pending.currentData()
        if key:
            self.jobs.run("review-reconcile", key, done=lambda result: self.operation_result(key, result))

    def cancel_review(self):
        key = self.pending.currentData()
        if key:
            self.jobs.run("review-cancel", key, confirm=True, done=lambda result: self.operation_result(key, result))

    def operation_result(self, key, payload):
        if not payload or payload.get("operation_id") != key:
            payload = {"outcome": "desconhecido", "operation_id": key,
                       "reason": "resposta ausente ou de outro código; não repetir a operação"}
        self.retained(payload)

    def show_retention(self, payload):
        if self._stopped: return
        value = payload or {}
        if "runs" in value:
            self.retention.setText(f"Temporários próprios: {value['runs']}/{value['limit']} · " + str(value.get("archive", "")))
        else:
            self.retention.setText("Retenção desconhecida: " + str(value.get("reason", "resposta ausente")))

    def retained(self, payload):
        if self._stopped: return
        self.operation_status.setText(str((payload or {}).get("outcome", "")) + " · " +
                                     str((payload or {}).get("reason", "resultado desconhecido; verificar novamente")))
        if (payload or {}).get("operation_id"):
            if payload.get("outcome") in ("sucesso", "recusa", "cancelamento"):
                self.operation_verified.emit(payload)
            self.jobs.run("review-pending", "", done=self.show_pending)
        if "archived" in (payload or {}):
            self.jobs.run("jobs-status", "", done=self.show_retention)

    def changed(self, checked):
        if self._stopped: return
        self.choice.setEnabled(False)
        self.jobs.run("startup-enable" if checked else "startup-disable", "", confirm=True, done=self.done)

    def done(self, payload):
        if self._stopped: return
        self.choice.setEnabled(True)
        if type((payload or {}).get("enabled")) is bool:
            self.choice.setTristate(False)
            self.choice.setChecked(payload["enabled"])
        else:
            self.choice.setTristate(True)
            self.choice.setCheckState(Qt.CheckState.PartiallyChecked)
            self.choice.setEnabled(False)
        if payload and "effective" in payload:
            self.status.setText("Preferência: " + ("ligada" if payload["enabled"] else "desligada") +
                                " · autostart: " + ("configurado" if payload["configured"] else "ainda não configurado") +
                                " · monitor: " + str(payload.get("service", {}).get("state", "desconhecido")) +
                                " · monitor no login: " + ("ligado" if payload.get("service", {}).get("enabled") else "não comprovado/desligado") +
                                (" · " + payload["reason"] if payload.get("reason") else ""))
        else:
            self.status.setText(str((payload or {}).get("outcome", "desconhecido")) + " · " +
                                str((payload or {}).get("reason", "resposta não comprovada; verificar novamente")))

    def stop(self):
        self._stopped = True
        self.jobs.shutdown()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)
