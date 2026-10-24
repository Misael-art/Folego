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

JSON_ACTIONS = ("plan", "ledger", "release", "restore", "expire", "recover")
SAMPLES_KEPT = 600  # 20 min de poller de 2 s; a janela do ETA é de 15 min
PENDING = "ainda não analisado — use Atualizar plano."
LOADING = "consultando o tmpfs (dry-run, nada é movido)…"
VOLUME_COLUMNS = (("path", "volume"), ("fs_type", "tipo"), ("total", "total"),
                  ("used", "usado"), ("avail", "livre"), ("bar", "ocupação"),
                  ("eta", "lotar em"))
PLAN_COLUMNS = (("path", "item"), ("size", "tamanho"), ("age", "idade"),
                ("holders", "donos"), ("state", "estado"), ("act", ""))
LEDGER_COLUMNS = (("entry_id", "id"), ("state", "estado"), ("size", "tamanho"),
                  ("src", "origem"), ("act", ""))


def argv_for(acao: str, target: str = "", confirm: bool = False) -> list:
    argv = [sys.executable, "-m", "folego", "tmpfs", acao]
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
    """Preenche e devolve os botões da coluna de ato, na ordem das linhas.

    As células são **reutilizadas** quando o poll traz o mesmo número de linhas:
    criar um `QProgressBar`/`QPushButton` novo a cada amostra deixava um widget
    órfão por volume (visto no ensaio F8: 20 mil amostras → milhares de widgets e
    RSS crescendo). O botão guarda a linha/ação atuais como atributos para o
    callback continuar correto sem reconectar o sinal a cada atualização.
    """
    table.setRowCount(len(rows))
    buttons = []
    for position, row in enumerate(rows):
        for column, (key, _) in enumerate(columns):
            if key == "bar":
                bar = table.cellWidget(position, column)
                if not isinstance(bar, QProgressBar):
                    bar = QProgressBar(table)
                    bar.setRange(0, 100)
                    bar.setTextVisible(False)
                    table.setCellWidget(position, column, bar)
                bar.setValue(row["pct"])
            elif key == "act":
                button = table.cellWidget(position, column)
                if not isinstance(button, QPushButton):
                    button = QPushButton(label, table)
                    button.clicked.connect(
                        lambda _=False, b=button: b._folego_action(b._folego_row))
                    table.setCellWidget(position, column, button)
                button.setText(label)
                button._folego_action = action
                button._folego_row = row
                buttons.append(button)
            else:
                item = table.item(position, column)
                if item is None:
                    item = QTableWidgetItem()
                    table.setItem(position, column, item)
                item.setText(str(row.get(key, "")))
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
        self.victims: list[dict] = []
        self._plan_ok = False
        self._uncertain_text = ""
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
        self.recover_button = QPushButton("Recuperar liberações inacabadas")
        self.recover_button.clicked.connect(self.recover_clicked)
        self.recover_button.setEnabled(False)
        self.recover_button.setToolTip(
            "nenhuma entrada staging no ledger: não há liberação inacabada")
        bar = QHBoxLayout()
        bar.addWidget(self.refresh_button)
        bar.addWidget(self.expire_button)
        bar.addWidget(self.recover_button)
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
            if volume.quality != "ok":
                self._samples.pop(volume.path, None)
                self.volume_rows.append({"path": volume.path, "fs_type": volume.fs_type,
                                         "total": "desconhecido", "used": "desconhecido",
                                         "avail": "desconhecido", "pct": 0,
                                         "eta": f"coleta falhou: {volume.error}"})
                continue
            series = self._samples.setdefault(volume.path, [])
            series.append((ts, volume.used_bytes))
            del series[:-SAMPLES_KEPT]
            hours = trend.eta_hours(tuple(series), volume.total_bytes, now=ts)
            self.volume_rows.append({
                "path": volume.path, "fs_type": volume.fs_type,
                "total": fmt_bytes(volume.total_bytes),
                "used": fmt_bytes(volume.used_bytes),
                "avail": fmt_bytes(volume.avail_bytes),
                "pct": round(volume.used_frac * 100),
                "eta": "—" if hours is None else _human_eta(hours)})
        _fill(self.volume_table, VOLUME_COLUMNS, self.volume_rows)
        unknown = [volume for volume in volumes if volume.quality != "ok"]
        if unknown:
            self.pressure.setText("capacidade desconhecida: " + "; ".join(
                f"{volume.path}: {volume.error}" for volume in unknown))
            return
        if not self.volume_rows:
            self.pressure.setText("nenhum volume da watch-list montado")
            return
        worst = self.volume_rows[0]
        lotar = "" if worst["eta"] == "—" else f" · lota em {worst['eta']}"
        # inodes são um teto separado dos bytes: um tmpfs pode ter folga de espaço
        # e ainda recusar arquivos novos.
        inode_worst = max((v for v in volumes if v.inodes_total),
                          key=lambda v: v.inodes_frac, default=None)
        inodes = ""
        if inode_worst is not None and inode_worst.inodes_frac >= 0.75:
            inodes = (f" · inodes de {inode_worst.path} a "
                      f"{round(inode_worst.inodes_frac * 100)}%")
        self.pressure.setText(f"pior volume: {worst['path']} a {worst['pct']}%{lotar}{inodes}")

    def refresh(self):
        self.summary.setText(LOADING)
        self._jobs.run("plan", "", done=self.show_plan)
        self._jobs.run("ledger", "", done=self.show_ledger)

    def show_plan(self, payload):
        if not payload or "reclaimable" not in payload:
            reason = (payload or {}).get("reason") or "o filho não respondeu"
            self._plan_ok = False
            self.plan_rows, self.release_buttons = [], []
            self.plan_table.setRowCount(0)
            self.summary.setText("sem plano")
            self.status.setText(f"não foi possível planejar: {reason}")
            self._preserve_uncertain()
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
        inconsistente = payload["scanned_entries"] != len(candidates) + len(protected)
        self._plan_ok = not inconsistente
        # R07: a interface não oferece uma ação que o executor já sabe bloquear —
        # item protegido e plano inconsistente desabilitam o botão, com o motivo.
        for row, button in zip(self.plan_rows, self.release_buttons):
            if inconsistente:
                button.setEnabled(False)
                button.setToolTip("plano inconsistente: a contagem não fechou — "
                                  "nada deve ser liberado")
            elif not row["ok"]:
                button.setEnabled(False)
                button.setToolTip(row["reason"])
        if inconsistente:
            self.status.setText("aviso: a contagem não fechou — o plano é incompleto "
                                "e nada aqui deve ser liberado")
        else:
            self.status.setText("isto é um plano: nada foi movido. Liberar pede "
                                "confirmação, e o item volta por esta aba.")
        self._preserve_uncertain()

    def show_ledger(self, payload):
        if not payload or "records" not in payload:
            # leitura que falhou não é leitura vazia: o orçamento e as vítimas da
            # leitura anterior não podem continuar autorizando a aba a pedir o expire
            self.budget, self.victims = {}, []
            self.ledger_rows, self.restore_buttons = [], []
            self.ledger_table.setRowCount(0)
            self.recover_button.setEnabled(False)
            self.recover_button.setToolTip(
                "sem leitura do ledger: não há como provar uma liberação inacabada")
            self.budget_label.setText("sem leitura do ledger")
            self.status.setText(((payload or {}).get("reason")
                                 or "o filho não respondeu") + " (ledger)")
            self._preserve_uncertain()
            return
        self.budget = payload.get("budget") or {}
        self.victims = payload.get("victims") or []
        self.ledger_rows = [{"entry_id": r["entry_id"], "state": r["state"],
                             "size": fmt_bytes(r["bytes"]), "src": r["src"]}
                            for r in payload["records"]]
        # a linha `partial` mantém botão: quem recusa é o ato, com motivo — a aba
        # não inventa regra que o digest já aplica
        self.restore_buttons = _fill(self.ledger_table, LEDGER_COLUMNS,
                                     self.ledger_rows, action=self.restore_clicked,
                                     label="Restaurar")
        staging = [row for row in self.ledger_rows if row["state"] == "staging"]
        self.recover_button.setEnabled(bool(staging))
        self.recover_button.setToolTip(
            (f"{len(staging)} liberação(ões) inacabada(s): a origem viva permite "
             "descartar o clone; origem sumida é preservada para decisão manual"
             if staging else
             "nenhuma entrada staging no ledger: não há liberação inacabada"))
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
            f"{mais_velho} d · saiu da RAM e não voltou "
            f"{fmt_bytes(self.budget['freed_bytes'])} · folga "
            f"{fmt_bytes(self.budget['slack_bytes'])}{estouro}")
        self._preserve_uncertain()

    def _preserve_uncertain(self):
        if self._uncertain_text:
            self.status.setText(self._uncertain_text)
            for button in (*self.release_buttons, *self.restore_buttons,
                           self.expire_button, self.recover_button):
                button.setEnabled(False)

    @staticmethod
    def _plan_row(item):
        return {"path": item["path"], "bytes": item["bytes"],
                "size": fmt_bytes(item["bytes"]),
                "age": f"{item['age_days']:.0f} d",
                "holders": ", ".join(str(p) for p in item["holder_pids"]) or "nenhum",
                "state": "candidato" if item["ok"] else item["reason"],
                "ok": bool(item["ok"]), "reason": item["reason"],
                "item_id": item["item_id"]}

    # ----------------------------------------------------------------------- atos

    def release_clicked(self, row):
        if self._uncertain_text:
            return
        if not self._plan_ok:
            self.status.setText("bloqueado: a contagem do plano não fechou — nada "
                                "foi pedido ao executor")
            return
        if not row.get("ok"):
            self.status.setText(f"bloqueado: {row.get('reason') or 'item protegido'}"
                                " — nada foi pedido ao executor")
            return
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
        if self._uncertain_text:
            return
        if not self._confirm(
                "Devolver ao espaço temporário",
                f"Vou copiar {row['size']} de volta para\n  {row['src']}\n"
                "e apagar o clone na SSD depois que o hash bater. Se o caminho de "
                "destino virou ponto de montagem, a recusa vem antes de qualquer "
                "escrita."):
            self.status.setText(f"cancelado: nada foi devolvido ({row['entry_id']})")
            return
        self._jobs.run("restore", row["entry_id"], confirm=True, done=self.show_mutation)

    def recover_clicked(self):
        if self._uncertain_text:
            return
        staging = [row for row in self.ledger_rows if row["state"] == "staging"]
        if not staging:
            self.status.setText(
                "nada a recuperar: nenhuma liberação inacabada no ledger")
            return
        shown = staging[:8]
        lines = "\n".join(f"  · {row['entry_id']} · {row['src']} · {row['size']}"
                          for row in shown)
        extra = (f"\n  … e mais {len(staging) - len(shown)}"
                 if len(staging) > len(shown) else "")
        if not self._confirm(
                "Recuperar liberações inacabadas",
                f"Vou fechar {len(staging)} entrada(s) deixadas em `staging`:\n"
                f"{lines}{extra}\n\n"
                "Com a origem ainda viva, o clone inacabado é descartado e o "
                "caminho volta a ser liberável. Se a origem sumiu, o clone é "
                "preservado — pode ser a única cópia — e o caso fica para decisão "
                "manual. Nenhum conteúdo é apagado sem essa prova."):
            self.status.setText("cancelado: nada foi recuperado")
            return
        self._jobs.run("recover", "", confirm=True, done=self.show_mutation)

    def expire_clicked(self):
        if self._uncertain_text:
            return
        if not self.budget:
            self.status.setText("sem leitura do ledger: nada a expirar")
            return
        # R07: a confirmação lista as vítimas EFETIVAS (idade vencida ou excesso),
        # não o total retido — apagar "tudo" não é o que o ato faz
        victims = self.victims or []
        if not victims:
            self.status.setText(
                "nada a expirar: nenhuma entrada passou do orçamento "
                f"({fmt_bytes(self.budget.get('retained_bytes', 0))} retidos)")
            return
        total = sum(int(v.get("bytes", 0)) for v in victims)
        shown = victims[:8]
        lines = "\n".join(f"  · {v.get('entry_id')} · {fmt_bytes(int(v.get('bytes', 0)))}"
                          f" · {v.get('src')}" for v in shown)
        extra = f"\n  … e mais {len(victims) - len(shown)}" if len(victims) > len(shown) else ""
        if not self._confirm(
                "Expirar retenção (irreversível)",
                f"Vou apagar {len(victims)} item(ns) que passaram do orçamento "
                f"({self.budget.get('days', 0):g} dias ou "
                f"{fmt_bytes(self.budget.get('max_bytes', 0))}):\n{lines}{extra}\n\n"
                f"São {fmt_bytes(total)} no total. Isto é irreversível: o conteúdo "
                "não volta, e o histórico do ledger continua registrado."):
            self.status.setText("cancelado: nada foi expirado")
            return
        self._jobs.run("expire", "", confirm=True, done=self.show_mutation)

    def show_mutation(self, payload):
        if not payload or payload.get("outcome") == "desconhecido":
            payload = payload or {}
            self._uncertain_text = ("desconhecido: " + str(payload.get("reason") or "o filho não respondeu") +
                " · operação " + str(payload.get("operation_id") or "consulte o histórico") +
                " · não repetir antes de reconciliar")
            self._preserve_uncertain()
            return
        # entrega 7: parcial não é recusa — parte do efeito existe (ex.: clone na
        # SSD, origem intacta); o veredito traz os números do que de fato
        # aconteceu, e o rótulo diz que o caminho não fechou
        parcial = payload.get("outcome") == "parcial"
        if not payload.get("ok") and not parcial:
            label = "falha" if payload.get("outcome") == "falha" else "recusado"
            self.status.setText(f"{label}: "
                                f"{payload.get('reason') or 'motivo não informado'}")
            return
        rotulo = "parcial: " if parcial else ""
        acao = payload.get("acao", "")
        if acao == "release":
            # "liberado" (saiu da RAM) e "transferidos" (ocupa na SSD) são medidas
            # diferentes; a contabilidade fina (6b) acrescenta o alocado real e a
            # variação observada quando o payload os traz — payload antigo não
            # inventa número (ausente/None não vira zero)
            alocado = payload.get("allocated_bytes")
            observado = payload.get("ram_observed_bytes")
            detalhe = f" · {fmt_bytes(alocado)} alocados" if alocado is not None else ""
            if observado is not None:
                detalhe += f" · RAM {observado:+d} bytes"
            self.status.setText(f"{rotulo}liberado "
                                f"{fmt_bytes(payload['freed_bytes'])} de conteúdo · "
                                f"transferidos {fmt_bytes(payload['bytes'])} para a SSD"
                                f"{detalhe} · "
                                f"id {payload['entry_id']} · devolva por esta aba")
        elif acao == "restore":
            self.status.setText(f"{rotulo}devolvido {fmt_bytes(payload['bytes'])} para "
                                f"{payload['restored_to']}")
        elif acao == "recover":
            dropped = payload.get("dropped") or []
            kept = payload.get("kept") or []
            lines = [f"{rotulo}{payload.get('reason') or 'recuperação concluída'}",
                     f"descartados: {len(dropped)} · mantidos: {len(kept)}"]
            lines += [f"aviso: {line}" for line in payload.get("errors") or ()]
            lines += [f"manual: {line}" for line in payload.get("notes") or ()]
            self.status.setText("\n".join(lines))
        elif not payload.get("victims") and payload.get("reason"):
            # "nada vencido": o motivo do executor, não um "expirado 0 bytes" que
            # pareceria um ato que não aconteceu
            self.status.setText(f"{rotulo}{payload['reason']}")
        else:
            lines = [f"{rotulo}expirado {fmt_bytes(payload['freed_bytes'])} da SSD · "
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
