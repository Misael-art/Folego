"""M3 disk tab: show the dry-run plan the child produced, measure nothing here.

The plan comes from a subprocess running the same headless CLI a terminal would
use, so this tab cannot grow filesystem code of its own: it formats. Refused
targets stay on the list, because the guard saying "no" is information the user
needs in order to trust the numbers above it.
"""
import sys

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..actions.disk.planner import fmt_bytes

PENDING = "consultando o disco (dry-run, nada é escrito)…"
PLAN_ARGV = (sys.executable, "-m", "deck_wellness", "disk", "plan", "--json")
# (row key, column title); the last column is the state, derived per row
COLUMNS = (("path", "caminho"), ("size", "tamanho"), ("files", "arquivos"))


def plan_argv(acao: str, tuning_id: str, confirm: bool) -> list[str]:
    """TuneJobs argv_factory for the one read-only act this tab performs."""
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
    def __init__(self, *, jobs, parent=None):
        super().__init__(parent)
        self._jobs = jobs
        self.rows: list[dict] = []
        self.thumbnails_kb: int | None = None

        self.summary = QLabel(PENDING)
        self.summary.setWordWrap(True)
        self.table = QTableWidget(0, len(COLUMNS) + 1)
        self.table.setHorizontalHeaderLabels([title for _, title in COLUMNS] + ["estado"])
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.refresh_button = QPushButton("Reconsultar o disco")
        self.refresh_button.clicked.connect(self.refresh)
        bar = QHBoxLayout()
        bar.addWidget(self.refresh_button)
        bar.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.status)
        layout.addLayout(bar)

    # -------------------------------------------------------------------- reading

    def refresh(self):
        self.summary.setText(PENDING)
        self._jobs.run("plan", "disk", done=self.show_plan)

    def show_plan(self, payload):
        if not payload or "items" not in payload:
            reason = (payload or {}).get("reason") or "o filho não respondeu"
            self.rows = []
            self.thumbnails_kb = None
            self.table.setRowCount(0)
            self.summary.setText("sem plano")
            self.status.setText(f"não foi possível planejar: {reason}")
            return

        items = sorted(payload["items"],
                       key=lambda i: (-i.get("bytes", 0), i.get("path", "")))
        self.rows = [{"path": i.get("path", "—"),
                      "bytes": int(i.get("bytes", 0)),
                      "size": fmt_bytes(i.get("bytes", 0)),
                      "files": str(i.get("files", 0)),
                      "label": i.get("label", ""),
                      "reason": i.get("reason", ""),
                      "state": state_of(i),
                      "reclaimable": bool(i.get("reclaimable"))} for i in items]
        self._fill_table()

        reclaimable = sum(i.get("bytes", 0) for i in items if i.get("reclaimable"))
        self.summary.setText(
            f"recuperáveis {fmt_bytes(reclaimable)} em {len(self.rows)} item(ns) · "
            f"lidos {fmt_bytes(payload.get('scanned_bytes', 0))}")
        self.status.setText(
            "isto é um plano: nada foi movido. Liberar de forma reversível é ato de "
            "terminal, com confirmação — deck-wellness disk quarantine <caminho> "
            "--confirmar.")
        thumb = next((i for i in items if i.get("target_id") == "thumbnails"), None)
        self.thumbnails_kb = None if thumb is None else thumb.get("bytes", 0) // 1024

    def _fill_table(self):
        self.table.setRowCount(len(self.rows))
        for row, item in enumerate(self.rows):
            for column, (key, _) in enumerate(COLUMNS):
                self.table.setItem(row, column, QTableWidgetItem(item[key]))
            self.table.setItem(row, len(COLUMNS), QTableWidgetItem(item["state"]))
        self.table.resizeColumnsToContents()
