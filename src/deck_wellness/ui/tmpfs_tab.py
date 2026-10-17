"""M7 tab: read what the child answered, ask before any RAM is freed.

Nothing here walks a tree or opens /proc — the volumes arrive from the poller as
plain tuples and the plan/ledger come from a killable child running the same
headless CLI a TTY would use. The ETA is extrapolation over the samples this
widget collected; a refusal from the child is printed as a refusal, never as a
silent "nothing happened" that could be read as success.
"""
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QProgressBar, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..actions.disk.planner import fmt_bytes
from ..actions.tmpfs import trend

JSON_ACTIONS = ("plan", "ledger", "release", "restore", "expire")
SAMPLES_KEPT = 600  # 20 min de poller de 2 s; a janela do ETA é de 15 min
PENDING = "consultando o tmpfs (dry-run, nada é movido)…"
VOLUME_COLUMNS = (("path", "volume"), ("fs_type", "tipo"), ("total", "total"),
                  ("used", "usado"), ("avail", "livre"), ("bar", "ocupação"),
                  ("eta", "lotar em"))
PLAN_COLUMNS = (("path", "item"), ("size", "tamanho"), ("age", "idade"),
                ("holders", "donos"), ("state", "estado"), ("act", ""))
LEDGER_COLUMNS = (("entry_id", "id"), ("state", "estado"), ("size", "tamanho"),
                  ("src", "origem"), ("act", ""))


def argv_for(acao: str, target: str = "", confirm: bool = False) -> list:
    argv = [sys.executable, "-m", "deck_wellness", "tmpfs", acao]
    if target:
        argv.append(str(target))
    if acao in JSON_ACTIONS:
        argv.append("--json")
    if confirm:
        argv.append("--confirmar")
    if acao == "expire" and confirm:
        argv.append("--irreversivel")
    return argv


def _human_eta(hours: float) -> str:
    if hours >= 24:
        return f"{hours / 24:.0f} dias"
    if hours >= 1:
        return f"{hours:.1f} h".replace(".", ",")
    return f"{hours * 60:.0f} min"


def _table(columns):
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels([title for _, title in columns])
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return table


def _fill(table, columns, rows, *, action=None, label=""):
    """Preenche e devolve os botões da coluna de ato, na ordem das linhas."""
    table.setRowCount(len(rows))
    buttons = []
    for position, row in enumerate(rows):
        for column, (key, _) in enumerate(columns):
            if key == "bar":
                bar = QProgressBar(table)
                bar.setRange(0, 100)
                bar.setTextVisible(False)
                bar.setValue(row["pct"])
                table.setCellWidget(position, column, bar)
            elif key == "act":
                button = QPushButton(label, table)
                button.clicked.connect(
                    lambda _=False, r=row, a=action: a(r))
                buttons.append(button)
                table.setCellWidget(position, column, button)
            else:
                table.setItem(position, column, QTableWidgetItem(str(row.get(key, ""))))
    return buttons


class TmpfsTab(QWidget):
    def __init__(self, *, jobs, confirm_fn=None, parent=None):
        super().__init__(parent)
        self._jobs = jobs
        self._confirm = confirm_fn or self._ask_dialog
        self._samples: dict[str, list] = {}
        self.volume_rows: list[dict] = []
        self.plan_rows: list[dict] = []
        self.ledger_rows: list[dict] = []
        self.budget: dict = {}
        self.release_buttons: list[QPushButton] = []
        self.restore_buttons: list[QPushButton] = []

        self.pressure = QLabel("nenhum volume da watch-list montado")
        self.pressure.setWordWrap(True)
        self.volume_table = _table(VOLUME_COLUMNS)
        self.summary = QLabel(PENDING)
        self.summary.setWordWrap(True)
        self.plan_table = _table(PLAN_COLUMNS)
        self.budget_label = QLabel("sem leitura do ledger")
        self.budget_label.setWordWrap(True)
        self.ledger_table = _table(LEDGER_COLUMNS)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.refresh_button = QPushButton("Atualizar plano")
        self.refresh_button.clicked.connect(self.refresh)
        self.expire_button = QPushButton("Expirar o excedente do orçamento")
        self.expire_button.clicked.connect(self.expire_clicked)
        bar = QHBoxLayout()
        bar.addWidget(self.refresh_button)
        bar.addWidget(self.expire_button)
        bar.addStretch(1)

        layout = QVBoxLayout(self)
        for widget in (self.pressure, self.volume_table, self.summary, self.plan_table,
                       self.budget_label, self.ledger_table, self.status):
            layout.addWidget(widget)
        layout.addLayout(bar)

    # -------------------------------------------------------------------- leitura

    def show_volumes(self, volumes, ts=None):
        """O poller traz tuplas planas; a aba só formata e lembra das amostras."""
        ts = time.time() if ts is None else ts
        self.volume_rows = []
        for volume in sorted(volumes, key=lambda v: v.used_frac, reverse=True):
            series = self._samples.setdefault(volume.path, [])
            series.append((ts, volume.used_bytes))
            del series[:-SAMPLES_KEPT]
            hours = trend.eta_hours(tuple(series), volume.total_bytes, now=ts)
            self.volume_rows.append({
                "path": volume.path, "fs_type": volume.fs_type,
                "total": fmt_bytes(volume.total_bytes), "used": fmt_bytes(volume.used_bytes),
                "avail": fmt_bytes(volume.avail_bytes),
                "pct": round(volume.used_frac * 100),
                "eta": "—" if hours is None else _human_eta(hours)})
        _fill(self.volume_table, VOLUME_COLUMNS, self.volume_rows)
        if not self.volume_rows:
            self.pressure.setText("nenhum volume da watch-list montado")
            return
        worst = self.volume_rows[0]
        lotar = "" if worst["eta"] == "—" else f" · lota em {worst['eta']}"
        self.pressure.setText(f"pior volume: {worst['path']} a {worst['pct']}%{lotar}")

    def refresh(self):
        self.summary.setText(PENDING)
        self._jobs.run("plan", "", done=self.show_plan)
        self._jobs.run("ledger", "", done=self.show_ledger)

    def show_plan(self, payload):
        if not payload or "reclaimable" not in payload:
            reason = (payload or {}).get("reason") or "o filho não respondeu"
            self.plan_rows, self.release_buttons = [], []
            self.plan_table.setRowCount(0)
            self.summary.setText("sem plano")
            self.status.setText(f"não foi possível planejar: {reason}")
            return
        candidates, protected = payload["reclaimable"], payload["protected"]
        self.plan_rows = [self._plan_row(i) for i in candidates] + \
                         [self._plan_row(i) for i in protected]
        self.release_buttons = _fill(self.plan_table, PLAN_COLUMNS, self.plan_rows,
                                     action=self.release_clicked, label="Liberar")
        self.summary.setText(
            f"liberáveis {fmt_bytes(payload['total_bytes'])} em {len(candidates)} "
            f"item(ns) · protegidos {len(protected)} · lidos "
            f"{payload['scanned_entries']} · impressão {payload['digest'][:16]}")
        if payload["scanned_entries"] != len(candidates) + len(protected):
            self.status.setText("aviso: a contagem não fechou — o plano é incompleto "
                                "e nada aqui deve ser liberado")
        else:
            self.status.setText("isto é um plano: nada foi movido. Liberar pede "
                                "confirmação, e o item volta por esta aba.")

    def show_ledger(self, payload):
        if not payload or "records" not in payload:
            self.ledger_rows, self.restore_buttons = [], []
            self.ledger_table.setRowCount(0)
            self.budget_label.setText("sem leitura do ledger")
            self.status.setText(((payload or {}).get("reason")
                                 or "o filho não respondeu") + " (ledger)")
            return
        self.budget = payload.get("budget") or {}
        self.ledger_rows = [{"entry_id": r["entry_id"], "state": r["state"],
                             "size": fmt_bytes(r["bytes"]), "src": r["src"]}
                            for r in payload["records"]]
        # a linha `partial` mantém botão: quem recusa é o ato, com motivo — a aba
        # não inventa regra que o digest já aplica
        self.restore_buttons = _fill(self.ledger_table, LEDGER_COLUMNS,
                                     self.ledger_rows, action=self.restore_clicked,
                                     label="Restaurar")
        mais_velho = f"{self.budget['oldest_days']:.1f}".replace(".", ",")
        # o aviso de estouro do `ledger` humano sai pelo stderr, e o --json não o emite:
        # a aba só fala por JSON, então quem tem de derivar o estouro é ela
        max_bytes = self.budget.get("max_bytes")
        estouro = (" · a retenção estourou o orçamento"
                   if max_bytes is not None and
                      self.budget.get("retained_bytes", 0) > max_bytes else "")
        self.budget_label.setText(
            f"retido {fmt_bytes(self.budget['retained_bytes'])} na SSD em "
            f"{self.budget['retained_count']} item(ns) · o mais velho "
            f"{mais_velho} d · RAM liberada "
            f"{fmt_bytes(self.budget['freed_bytes'])} · folga "
            f"{fmt_bytes(self.budget['slack_bytes'])}{estouro}")

    @staticmethod
    def _plan_row(item):
        return {"path": item["path"], "bytes": item["bytes"],
                "size": fmt_bytes(item["bytes"]),
                "age": f"{item['age_days']:.0f} d",
                "holders": ", ".join(str(p) for p in item["holder_pids"]) or "nenhum",
                "state": "candidato" if item["ok"] else item["reason"],
                "item_id": item["item_id"]}

    # ----------------------------------------------------------------------- atos

    def release_clicked(self, row):
        if not self._confirm(
                "Liberar espaço em RAM",
                f"Vou tirar {row['size']} de RAM movendo\n  {row['path']}\n"
                "para a quarentena na SSD, verificando hash por arquivo antes de "
                "apagar a origem.\n\n"
                f"Processos com arquivo aberto aqui: {row['holders']}.\n"
                "Volta por esta aba, com o id do registro — e enquanto estiver retido "
                "conta no orçamento de retenção."):
            self.status.setText(f"cancelado: nada foi liberado ({row['path']})")
            return
        self._jobs.run("release", row["path"], confirm=True, done=self.show_mutation)

    def restore_clicked(self, row):
        if not self._confirm(
                "Devolver ao espaço temporário",
                f"Vou copiar {row['size']} de volta para\n  {row['src']}\n"
                "e apagar o clone na SSD depois que o hash bater. Se o caminho de "
                "destino virou ponto de montagem, a recusa vem antes de qualquer "
                "escrita."):
            self.status.setText(f"cancelado: nada foi devolvido ({row['entry_id']})")
            return
        self._jobs.run("restore", row["entry_id"], confirm=True, done=self.show_mutation)

    def expire_clicked(self):
        if not self.budget:
            self.status.setText("sem leitura do ledger: nada a expirar")
            return
        retained = fmt_bytes(self.budget.get("retained_bytes", 0))
        if not self._confirm(
                "Expirar retenção (irreversível)",
                f"Vou apagar {retained} que estão retidos na SSD além do orçamento "
                f"({self.budget.get('days', 0):g} dias ou "
                f"{fmt_bytes(self.budget.get('max_bytes', 0))}).\n\n"
                "Isto é irreversível: o conteúdo não volta, e o histórico do ledger "
                "continua registrado."):
            self.status.setText("cancelado: nada foi expirado")
            return
        self._jobs.run("expire", "", confirm=True, done=self.show_mutation)

    def show_mutation(self, payload):
        if not payload:
            self.status.setText("o filho não respondeu; nada é considerado feito")
            return
        if not payload.get("ok"):
            self.status.setText("recusado: "
                                f"{payload.get('reason') or 'motivo não informado'}")
            return
        acao = payload.get("acao", "")
        if acao == "release":
            self.status.setText(f"liberado {fmt_bytes(payload['freed_bytes'])} de RAM · "
                                f"id {payload['entry_id']} · devolva por esta aba")
        elif acao == "restore":
            self.status.setText(f"devolvido {fmt_bytes(payload['bytes'])} para "
                                f"{payload['restored_to']}")
        else:
            lines = [f"expirado {fmt_bytes(payload['freed_bytes'])} da SSD · "
                     f"{len(payload.get('victims') or ())} item(ns)"]
            lines += [f"aviso: {line}" for line in payload.get("errors") or ()]
            self.status.setText("\n".join(lines))
        # re-leitura pelo loop de eventos: um veredito novo não pode nascer de dentro
        # do callback do filho anterior
        QTimer.singleShot(0, self.refresh)

    def _ask_dialog(self, title: str, text: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes |
                               QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes
