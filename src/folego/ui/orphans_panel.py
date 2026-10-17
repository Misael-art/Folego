"""M4 panel: prove it, show it, and only then signal it.

The window hands this widget plain data (candidates and groups already filtered
by the core rules); this widget decides what to ask and whom to call. It never
reads the system itself, and every act goes through an injected callback, so the
confirmation path is testable without touching a live process.
"""
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..actions.disk.planner import fmt_bytes


def _rss(rss_kb: int) -> str:
    return fmt_bytes(rss_kb * 1024)


class OrphansPanel(QWidget):
    def __init__(self, *, confirm_fn=None, on_terminate=None, on_force=None,
                 on_group=None, parent=None):
        super().__init__(parent)
        self._confirm = confirm_fn or self._ask_dialog
        self._on_terminate = on_terminate
        self._on_force = on_force
        self._on_group = on_group
        self._candidates: list = []
        self._groups: tuple = ()
        self._group_index = 0
        self._survivors: list = []
        self._survivors_from_group = False

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["pid", "app", "RAM", "ocioso", "estado"])
        self.tree.setSelectionMode(self.tree.SelectionMode.SingleSelection)
        self.status_label = QLabel("Aguardando observações: órfão comprovado exige "
                                   "pai morto, CPU parada e tempo olhando.")
        self.status_label.setWordWrap(True)

        self.term_button = QPushButton("Encerrar selecionado (SIGTERM)")
        self.force_button = QPushButton("Forçar sobreviventes (SIGKILL)")
        self.group_picker = QComboBox()
        self.group_picker.setEnabled(False)
        self.group_picker.currentIndexChanged.connect(self._group_choice_changed)
        self.group_button = QPushButton("Encerrar grupo")
        self.term_button.clicked.connect(self.terminate_clicked)
        self.force_button.clicked.connect(self.force_clicked)
        self.group_button.clicked.connect(self.group_clicked)
        self.force_button.setEnabled(False)
        self.group_button.setEnabled(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.term_button)
        buttons.addWidget(self.force_button)
        buttons.addWidget(self.group_picker)
        buttons.addWidget(self.group_button)
        layout = QVBoxLayout()
        layout.addWidget(self.tree)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)
        self.setLayout(layout)

    # ------------------------------------------------------------------ listing

    def show_candidates(self, candidates):
        # a poll lands while the user is pointing at a row: keep that choice
        keep = self._selected_pid()
        self._candidates = list(candidates)
        self._survivors = []
        self._survivors_from_group = False
        self.tree.clear()
        for c in self._candidates:
            QTreeWidgetItem(self.tree, [str(c.pid), c.comm, _rss(c.rss_kb),
                                        f"{c.idle_s:.0f} s",
                                        f"{c.state} · pai {c.ppid}"])
        if keep is not None:
            for row, c in enumerate(self._candidates):
                if c.pid == keep:
                    self.select(row)
                    break
        if not self._candidates:
            self.status_label.setText(
                "Sem órfãos: todo processo observado tem pai vivo, consome CPU ou "
                "está na lista protegida.")
        self.force_button.setEnabled(False)

    def show_groups(self, groups):
        self._groups = tuple(groups)
        keep = self._groups[self._group_index].group if self._groups else None
        self.group_picker.blockSignals(True)
        self.group_picker.clear()
        for target in self._groups:
            self.group_picker.addItem(
                f"{target.label} · {len(target.members)} processos · "
                f"{_rss(target.total_rss_kb)}")
        self.group_picker.blockSignals(False)
        if not self._groups:
            self._group_index = 0
            self.group_picker.setEnabled(False)
            self.group_button.setEnabled(False)
            self.group_button.setText("Encerrar grupo")
            return
        self._group_index = self._kept_index(keep)
        self.group_picker.setEnabled(len(self._groups) > 1)
        self.group_button.setEnabled(True)
        self.group_picker.setCurrentIndex(self._group_index)
        self._group_choice_changed(self._group_index)

    def _kept_index(self, group_key) -> int:
        if group_key is not None:
            for index, target in enumerate(self._groups):
                if target.group == group_key:
                    return index
        return 0

    def current_group(self):
        return self._groups[self._group_index]

    def group_options(self) -> list[str]:
        return [target.label for target in self._groups]

    def choose_group(self, index: int):
        self.group_picker.setCurrentIndex(index)

    def _group_choice_changed(self, index: int):
        if not self._groups:
            return
        self._group_index = max(0, min(index, len(self._groups) - 1))
        target = self.current_group()
        self.group_button.setText(
            f"Encerrar grupo {target.label} · {len(target.members)} processos · "
            f"{_rss(target.total_rss_kb)}")

    def rows(self) -> list[dict]:
        return [{"pid": self._candidates[i].pid,
                 "comm": self.tree.topLevelItem(i).text(1),
                 "rss": self.tree.topLevelItem(i).text(2),
                 "idle": self.tree.topLevelItem(i).text(3),
                 "state": self.tree.topLevelItem(i).text(4)}
                for i in range(self.tree.topLevelItemCount())]

    def group_text(self) -> str:
        return self.group_button.text()

    def status(self) -> str:
        return self.status_label.text()

    def survivors(self) -> list[int]:
        return [c.pid for c in self._survivors]

    def select(self, index: int):
        self.tree.setCurrentItem(self.tree.topLevelItem(index))

    # ------------------------------------------------------------------- actions

    def _selected_pid(self):
        row = self.tree.currentIndex().row()
        if 0 <= row < len(self._candidates):
            return self._candidates[row].pid
        return None

    def terminate_clicked(self):
        pid = self._selected_pid()
        if pid is None:
            self.status_label.setText("Selecione uma linha antes de encerrar.")
            return
        candidate = next(c for c in self._candidates if c.pid == pid)
        command = " ".join(candidate.cmdline)[:160] or "—"
        if not self._confirm(
                f"Encerrar pid {candidate.pid} ({candidate.comm}, "
                f"{_rss(candidate.rss_kb)})?\n"
                f"Comando: {command}\n"
                f"Sob cuidado de: pid {candidate.ppid}.\n"
                f"SIGTERM dá ao processo a chance de salvar e fechar sozinho."):
            self._cancelled()
            return
        self._after(self._call(self._on_terminate, [candidate]), [candidate],
                    sigterm=True)

    def force_clicked(self):
        if not self._survivors:
            return
        pids = " ".join(str(c.pid) for c in self._survivors)
        if not self._confirm(
                f"SIGKILL em {pids}? O processo é cortado sem chance de salvar o "
                f"que estiver na memória."):
            self._cancelled()
            return
        self._after(self._call(self._on_force, self._survivors), self._survivors,
                    sigterm=False)

    def group_clicked(self):
        if not self._groups:
            return
        target = self.current_group()
        pids = " ".join(str(member.pid) for member in target.members)
        if not self._confirm(
                f"Encerrar o grupo {target.label}: {len(target.members)} processos · "
                f"pids {pids} · {_rss(target.total_rss_kb)} de RAM.\n"
                f"Janelas abertas nesse navegador serão fechadas."):
            self._cancelled()
            return
        self._after(self._call(self._on_group, target), list(target.members),
                    sigterm=True, from_group=True)

    # ---------------------------------------------------------------- plumbing

    def _call(self, callback, payload):
        if callback is None:
            self.status_label.setText("Nenhum executor ligado: nada foi sinalizado.")
            return []
        if callback is self._on_force:
            # a browser child always has a live parent: demanding orphanhood there
            # would leave SIGTERM-refused members with no escalation at all.
            return callback(payload, confirm=True,
                            require_orphan=not self._survivors_from_group)
        if callback is self._on_group:
            return callback(payload, confirm=True)
        return callback(payload)

    def _cancelled(self):
        self.status_label.setText("Cancelado: nada foi sinalizado.")

    def _after(self, results, payload, *, sigterm: bool, from_group: bool = False):
        if not results:
            return
        refused = [r for r in results if not r.ok]
        by_pid = {item.pid: item for item in payload}
        self._survivors = [by_pid[r.pid] for r in refused if r.pid in by_pid]
        self._survivors_from_group = from_group
        self.force_button.setEnabled(bool(self._survivors) and sigterm)
        if refused:
            self.status_label.setText(
                "recusado: " + " · ".join(r.reason or "" for r in refused))
        else:
            self.status_label.setText(
                f"sinalizado: {len(results)} processo(s); a próxima leitura confirma "
                f"o efeito.")

    @staticmethod
    def _ask_dialog(text: str) -> bool:
        answer = QMessageBox.question(
            None, "Fôlego", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes
