"""Disk tab: a dry-run plan, then reversible quarantine, all through the CLI.

The plan and every mutation come from a killable child running the same headless
CLI a terminal would use. This widget formats; it never measures or moves a byte
itself. Refused targets stay on the list because the guard saying "no" is
information the user needs in order to trust the numbers above it. Quarantine
is reversible by construction: restore is offered only for entries the child
reported as ``stored`` and purge asks for an explicit irreversible confirmation.
"""
import sys
import json
from datetime import datetime

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..actions.disk.planner import fmt_bytes

PLAN_PENDING = "ainda não analisado — use Reconsultar o disco."
PLAN_LOADING = "consultando o disco (dry-run, nada é escrito)…"
QUARANTINE_PENDING = "quarentena ainda não consultada."
PLAN_ARGV = (sys.executable, "-m", "folego", "disk", "plan", "--json")
# (row key, column title); the last column is the state, derived per row
COLUMNS = (("path", "caminho"), ("size", "tamanho"), ("files", "arquivos"))
QUARANTINE_COLUMNS = (("name", "nome"), ("size", "tamanho"),
                      ("state", "estado"), ("original", "origem"))


def plan_argv(acao: str, target: str, confirm: bool) -> list[str]:
    """The one argv factory this tab uses for read and mutating disk acts.

    ``plan`` is the historical read-only call; ``list`` is the quarantine
    inventory; the three mutations always carry ``--json`` so the UI can tell a
    refusal from a completed move without parsing human prose.
    """
    argv = [sys.executable, "-m", "folego", "disk", acao]
    if acao == "quarantine-reviewed":
        from ..orchestration.models import ActionPlan
        plan = ActionPlan.from_dict(json.loads(target))
        argv = [sys.executable, "-m", "folego", "disk", "quarantine",
                plan.target.key, "--reviewed-plan", target, "--json"]
        if confirm:
            argv.append("--confirmar")
        return argv
    if acao in ("quarantine", "restore", "purge"):
        argv.append(str(target))
        argv.append("--json")
        if confirm:
            argv.append("--confirmar")
        if acao == "purge":
            argv.append("--irreversivel")
        return argv
    if acao == "list":
        argv.append("--json")
        return argv
    return list(PLAN_ARGV)


def state_of(item) -> str:
    """Why this row is (or is not) on the reclaimable list, in the user's words."""
    if item.get("reclaimable"):
        return "recuperável"
    reason = item.get("reason", "")
    if reason and reason != "ok":
        return reason
    if not item.get("bytes"):
        return "vazio"
    return f"intacto há {item.get('age_days', 0):.0f} dias"


class DiskTab(QWidget):
    def __init__(self, *, jobs, confirm_fn=None, parent=None):
        super().__init__(parent)
        self._jobs = jobs
        self._confirm = confirm_fn or self._ask_dialog
        self.rows: list[dict] = []
        self.quarantine_rows: list[dict] = []
        self.thumbnails_kb: int | None = None
        self._last_status = ""
        self._uncertain = False
        self._reviewed_operation = ""
        self._quarantine_loaded = False

        self.summary = QLabel(PLAN_PENDING)
        self.summary.setWordWrap(True)
        self.table = QTableWidget(0, len(COLUMNS) + 1)
        self.table.setHorizontalHeaderLabels([title for _, title in COLUMNS] + ["estado"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.refresh_button = QPushButton("Reconsultar o disco")
        self.refresh_button.clicked.connect(self.refresh)
        self.quarantine_button = QPushButton("Quarentenar selecionado (reversível)")
        self.quarantine_button.clicked.connect(self.quarantine_selected)
        self.quarantine_button.setEnabled(False)
        self.quarantine_button.setAccessibleName(
            "Mover o item selecionado para a quarentena reversível")
        bar = QHBoxLayout()
        bar.addWidget(self.refresh_button)
        bar.addWidget(self.quarantine_button)
        bar.addStretch(1)

        # ------------------------------------------------------------ quarantine
        self.quarantine_summary = QLabel(QUARANTINE_PENDING)
        self.quarantine_summary.setWordWrap(True)
        self.quarantine_table = QTableWidget(0, len(QUARANTINE_COLUMNS))
        self.quarantine_table.setHorizontalHeaderLabels(
            [title for _, title in QUARANTINE_COLUMNS])
        self.quarantine_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.quarantine_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self.quarantine_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        self.quarantine_table.verticalHeader().setVisible(False)
        self.quarantine_table.itemSelectionChanged.connect(
            self._q_selection_changed)
        self.quarantine_table.setAccessibleName(
            "Itens na quarentena reversível do disco")

        self.quarantine_list_button = QPushButton("Ver quarentena")
        self.quarantine_list_button.clicked.connect(self.refresh_quarantine)
        self.restore_button = QPushButton("Restaurar selecionado")
        self.restore_button.clicked.connect(self.restore_selected)
        self.restore_button.setEnabled(False)
        self.purge_button = QPushButton("Apagar de vez (irreversível)")
        self.purge_button.clicked.connect(self.purge_selected)
        self.purge_button.setEnabled(False)
        q_bar = QHBoxLayout()
        q_bar.addWidget(self.quarantine_list_button)
        q_bar.addWidget(self.restore_button)
        q_bar.addWidget(self.purge_button)
        q_bar.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 2)
        layout.addWidget(self.quarantine_summary)
        layout.addWidget(self.quarantine_table, 1)
        layout.addWidget(self.status)
        layout.addLayout(q_bar)
        layout.addLayout(bar)

    # -------------------------------------------------------------------- reading

    def refresh(self):
        self.summary.setText(PLAN_LOADING)
        self._jobs.run("plan", "disk", done=self.show_plan)

    def refresh_quarantine(self):
        self.quarantine_summary.setText("consultando a quarentena (nada é movido)…")
        self._jobs.run("list", "quarantine", done=self.show_quarantine)

    def show_plan(self, payload):
        if not payload or "items" not in payload:
            reason = (payload or {}).get("reason") or "o filho não respondeu"
            self.rows = []
            self.thumbnails_kb = None
            self.table.setRowCount(0)
            self.quarantine_button.setEnabled(False)
            self.summary.setText("sem plano")
            detail = f"não foi possível planejar: {reason}"
            if self._last_status:
                detail = f"{self._last_status} · {detail}"
            self.status.setText(detail)
            if not self._uncertain:
                self._last_status = ""
            return

        items = sorted(payload["items"],
                       key=lambda i: (-i.get("bytes", 0), i.get("path", "")))
        self.rows = [{"path": i.get("path", "—"),
                      "bytes": int(i.get("bytes", 0)),
                      "size": fmt_bytes(i.get("bytes", 0)),
                      "files": str(i.get("files", 0)),
                      "label": i.get("label", ""),
                      "target_id": i.get("target_id", ""),
                      "reason": i.get("reason", ""),
                      "state": state_of(i),
                      "action_plan": i.get("action_plan"),
                      "review_error": i.get("review_error", ""),
                      "reclaimable": bool(i.get("reclaimable"))} for i in items]
        self._fill_table()

        reclaimable = sum(i.get("bytes", 0) for i in items if i.get("reclaimable"))
        self.summary.setText(
            f"recuperáveis {fmt_bytes(reclaimable)} em {len(self.rows)} item(ns) · "
            f"lidos {fmt_bytes(payload.get('scanned_bytes', 0))}")
        plan_note = ("isto é um plano: nada foi movido. Quarentenar move o item "
                     "para um destino reversível; restaurar devolve ao caminho "
                     "original.")
        partial = [item for item in items
                   if item.get("truncated") or item.get("errors")]
        if partial:
            plan_note += (f" · plano parcial em {len(partial)} item(ns): a leitura "
                          "não cobriu tudo")
        self.status.setText(f"{self._last_status} · {plan_note}"
                            if self._last_status else plan_note)
        if not self._uncertain:
            self._last_status = ""
        thumb = next((i for i in items if i.get("target_id") == "thumbnails"), None)
        self.thumbnails_kb = None if thumb is None else thumb.get("bytes", 0) // 1024

    def show_quarantine(self, payload):
        self._quarantine_loaded = True
        if not payload or payload.get("ok") is False or "entries" not in payload:
            reason = (payload or {}).get("reason") or "o filho não respondeu"
            self.quarantine_rows = []
            self.quarantine_table.setRowCount(0)
            self.quarantine_summary.setText(f"quarentena ilegível: {reason}")
            self._q_selection_changed()
            return
        entries = sorted(payload.get("entries", []),
                         key=lambda e: (-int(e.get("observed_bytes") or
                                            e.get("bytes") or 0),
                                        str(e.get("original", ""))))
        self.quarantine_rows = [{
            "entry_id": str(e.get("entry_id", "")),
            "name": str(e.get("original", "")).rsplit("/", 1)[-1] or "—",
            "size": fmt_bytes(e.get("observed_bytes") or e.get("bytes") or 0),
            "state": str(e.get("state", "?")),
            "original": str(e.get("original", "—")),
            "stored": e.get("state") == "stored",
        } for e in entries]
        self.quarantine_table.setRowCount(len(self.quarantine_rows))
        for row, item in enumerate(self.quarantine_rows):
            for column, (key, _) in enumerate(QUARANTINE_COLUMNS):
                self.quarantine_table.setItem(
                    row, column, QTableWidgetItem(item[key]))
        self.quarantine_table.resizeColumnsToContents()
        if not self.quarantine_rows:
            self.quarantine_summary.setText(
                "quarentena vazia: nada foi movido para retenção reversível.")
        else:
            stored = sum(1 for item in self.quarantine_rows if item["stored"])
            self.quarantine_summary.setText(
                f"{len(self.quarantine_rows)} entrada(s) · {stored} restaurável(is) · "
                "restaurar exige o caminho de origem livre; apagar não tem volta.")
        self._q_selection_changed()

    def _fill_table(self):
        self.table.setRowCount(len(self.rows))
        for row, item in enumerate(self.rows):
            for column, (key, _) in enumerate(COLUMNS):
                self.table.setItem(row, column, QTableWidgetItem(item[key]))
            self.table.setItem(row, len(COLUMNS), QTableWidgetItem(item["state"]))
        self.table.resizeColumnsToContents()
        self._selection_changed()

    # ------------------------------------------------------------------- actions

    def _selected_plan(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.rows):
            return self.rows[row]
        return None

    def _selected_quarantine(self):
        row = self.quarantine_table.currentRow()
        if 0 <= row < len(self.quarantine_rows):
            return self.quarantine_rows[row]
        return None

    def _selection_changed(self):
        item = self._selected_plan()
        self.quarantine_button.setEnabled(bool(item and item["reclaimable"]) and not self._uncertain)

    def _q_selection_changed(self):
        item = self._selected_quarantine()
        useful = bool(item and item["stored"]) and not self._uncertain
        self.restore_button.setEnabled(useful)
        self.purge_button.setEnabled(useful)

    def quarantine_selected(self):
        if self._uncertain or getattr(self, "_quarantine_pending", False):
            return
        item = self._selected_plan()
        if item is None or not item["reclaimable"]:
            self._status("selecione um item recuperável antes de quarentenar.")
            return
        from ..orchestration.models import ActionPlan, ValidationError
        try:
            plan = ActionPlan.from_dict(item.get("action_plan") or {})
            if plan.action != "disk.quarantine" or plan.target.key != item["path"]:
                raise ValidationError("plano não corresponde ao item selecionado")
            if plan.expired():
                raise ValidationError("plano expirado; é necessária nova análise")
        except (ValueError, TypeError, ValidationError) as exc:
            self._status("revisão indisponível; reconsulte o disco: " +
                         (item.get("review_error") or str(exc)))
            return
        self._quarantine_pending = True
        if not self._confirm(
                f"Colocar {item['path']} ({item['size']}) em quarentena?\n"
                f"Plano {plan.operation_id} · válido até "
                f"{datetime.fromtimestamp(plan.expires_at).astimezone():%H:%M:%S}\n"
                "Efeito: o conteúdo é movido para retenção reversível e o caminho "
                "original fica livre. Nada é apagado; Restaurar devolve o item."):
            self._status("Cancelado: nada foi movido.")
            self._quarantine_pending = False
            return
        self._reviewed_operation = plan.operation_id
        self._jobs.run("quarantine-reviewed", json.dumps(plan.to_dict()), confirm=True,
                       done=self._mutation_done)

    def restore_selected(self):
        if self._uncertain:
            return
        item = self._selected_quarantine()
        if item is None or not item["stored"]:
            self._status("selecione uma entrada armazenada antes de restaurar.")
            return
        if not self._confirm(
                f"Restaurar {item['original']} a partir da quarentena?\n"
                "O conteúdo volta ao caminho original; a origem precisa estar "
                "livre e não ser substituída."):
            self._status("Cancelado: nada foi restaurado.")
            return
        self._jobs.run("restore", item["entry_id"], confirm=True,
                       done=self._mutation_done)

    def purge_selected(self):
        if self._uncertain:
            return
        item = self._selected_quarantine()
        if item is None or not item["stored"]:
            self._status("selecione uma entrada armazenada antes de apagar.")
            return
        if not self._confirm(
                f"Apagar de vez {item['original']} ({item['size']})?\n"
                "Esta ação é IRREVERSÍVEL: não haverá restauração. O item só pode "
                "ser apagado se ainda estiver íntegro e dentro do destino de "
                "retenção."):
            self._status("Cancelado: nada foi apagado.")
            return
        self._jobs.run("purge", item["entry_id"], confirm=True,
                       done=self._mutation_done)

    def _mutation_done(self, payload):
        self._quarantine_pending = False
        payload = payload or {}
        if not payload or payload.get("outcome") == "desconhecido":
            self._uncertain = True
            self._status("desconhecido: " + str(payload.get("reason") or "o filho não respondeu") +
                " · operação " + str(payload.get("operation_id") or self._reviewed_operation or "consulte o histórico") +
                " · não repetir antes de reconciliar")
            self.quarantine_button.setEnabled(False)
            self.restore_button.setEnabled(False)
            self.purge_button.setEnabled(False)
            return
        self._reviewed_operation = ""
        outcome = payload.get("outcome")
        ok = payload.get("ok")
        if outcome == "sucesso" or (not outcome and ok is True):
            self._last_status = (
                f"operação concluída: {payload.get('acao', 'disco')}.")
        elif outcome:
            self._last_status = (
                f"{outcome}: {payload.get('reason') or 'sem detalhe'}")
        else:
            self._last_status = (
                f"falha: {payload.get('reason') or 'o filho não respondeu'}")
        self.status.setText(self._last_status)
        self.refresh()
        self.refresh_quarantine()

    def _status(self, text: str):
        self._last_status = text
        self.status.setText(text)

    @staticmethod
    def _ask_dialog(text: str) -> bool:
        dialog = QMessageBox()
        dialog.setWindowTitle("Fôlego — disco")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(text)
        dialog.setMinimumWidth(520)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Confirmar")
        dialog.button(QMessageBox.StandardButton.No).setText("Cancelar")
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        answer = dialog.exec()
        return answer == QMessageBox.StandardButton.Yes
