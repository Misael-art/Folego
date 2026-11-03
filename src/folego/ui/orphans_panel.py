"""M4 panel: prove it, show it, and only then signal it.

The window hands this widget plain data (candidates and groups already filtered
by the core rules); this widget decides what to ask and whom to call. It never
reads the system itself, and every act goes through an injected callback, so the
confirmation path is testable without touching a live process.
"""
from concurrent.futures import Future
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QComboBox, QGridLayout, QLabel, QMessageBox,
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
        self._investigation: list = []
        self._groups: tuple = ()
        self._group_index = 0
        self._survivors: list = []
        self._survivors_from_group = False
        self._survivors_sigterm = False
        self._items: dict[tuple[int, int], QTreeWidgetItem] = {}
        self._pending = None
        self._unknown_operation = False

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["pid", "app", "RAM (RSS est.)", "ocioso", "estado"])
        self.tree.setSelectionMode(self.tree.SelectionMode.SingleSelection)
        self.status_label = QLabel("Aguardando observações: órfão comprovado exige "
                                   "pai morto, CPU parada e tempo olhando.")
        self.status_label.setWordWrap(True)
        # CPU ativa não satisfaz a regra de ociosidade, mas também não prova que
        # o processo é útil. Esta linha é só uma pista para o humano investigar;
        # não habilita Encerrar nem Forçar.
        self.investigation_label = QLabel("")
        self.investigation_label.setWordWrap(True)
        self.investigation_label.setAccessibleName(
            "Investigação de processos com CPU ativa")
        self.investigation_label.setVisible(False)
        # Seção de processos/sessões: o que está protegido e por quê. É leitura;
        # iniciar/encerrar sessão continua sendo ato explícito da CLI.
        self.protections_label = QLabel(
            "sessões: nenhuma lida ainda · exclusões: nenhuma lida ainda")
        self.protections_label.setObjectName("quality")
        self.protections_label.setWordWrap(True)
        self.protections_label.setAccessibleName("Sessões e exclusões ativas")

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

        buttons = QGridLayout()
        buttons.addWidget(self.term_button, 0, 0)
        buttons.addWidget(self.force_button, 0, 1)
        buttons.addWidget(self.group_picker, 1, 0)
        buttons.addWidget(self.group_button, 1, 1)
        layout = QVBoxLayout()
        layout.addWidget(self.tree)
        layout.addWidget(self.investigation_label)
        layout.addWidget(self.protections_label)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)
        self.setLayout(layout)

    # ------------------------------------------------------------------ listing

    def show_investigation(self, candidates):
        """Pistas com CPU ativa; não são oferecidas como órfãos comprovados."""
        self._investigation = list(candidates)
        if not self._investigation:
            self.investigation_label.clear()
            self.investigation_label.setVisible(False)
            return
        parts = []
        for item in self._investigation[:5]:
            cpu = f"{item.cpu_frac:.0f}%" if item.cpu_frac is not None else "?"
            parts.append(f"pid {item.pid} · {item.comm} · cpu {cpu}")
        extra = (f" · +{len(self._investigation) - 5} outro(s)"
                 if len(self._investigation) > 5 else "")
        self.investigation_label.setText(
            "Investigação possível (CPU ativa; abandono não provado): "
            + " · ".join(parts) + extra)
        self.investigation_label.setVisible(True)

    def show_protections(self, sessions, exclusions, *, error: str = ""):
        """Resumo honesto das proteções lidas nesta amostra.

        Uma leitura ilegível nunca aparece como "nenhuma sessão": o texto diz que
        a proteção não foi comprovada e que os candidatos foram ocultados.
        """
        sessions = tuple(sessions or ())
        exclusions = tuple(exclusions or ())
        if error:
            self.protections_label.setText(
                f"proteção não comprovada: {error}. Candidatos ocultados até a "
                "leitura voltar a funcionar.")
            return
        live = [s for s in sessions if not s.ended]
        by_state = {}
        for session in live:
            by_state[session.state] = by_state.get(session.state, 0) + 1
        state_text = ", ".join(f"{state} {count}"
                               for state, count in sorted(by_state.items()))
        keep = sum(1 for s in live if s.keep_active)
        artifacts = sum(len(s.artifacts) for s in sessions)
        parts = [f"sessões: {state_text or 'nenhuma ativa'}"
                 + (f" · {keep} com keep-active" if keep else "")
                 + (f" · {artifacts} artefato(s) registrado(s)" if artifacts else "")]
        if live:
            names = [f"pid {s.pid} {s.label or s.project or ''}".strip()
                     for s in live[:4]]
            parts.append(" · ".join(names) + (" · …" if len(live) > 4 else ""))
        ex_keep = sum(1 for item in exclusions if item.keep_active)
        parts.append(f"exclusões: {len(exclusions)}"
                     + (f" · {ex_keep} com keep-active" if ex_keep else ""))
        self.protections_label.setText(" · ".join(parts))

    def protections_text(self) -> str:
        return self.protections_label.text()

    def investigation_text(self) -> str:
        return self.investigation_label.text()

    def investigation_pids(self) -> list[int]:
        return [item.pid for item in getattr(self, "_investigation", [])]

    def show_candidates(self, candidates):
        # a poll lands while the user is pointing at a row: keep that choice
        keep = self._selected_pid()
        previous = {s.pid: s.starttime for s in self._survivors}
        previous_group = self._survivors_from_group
        self._candidates = list(candidates)
        # R10/entrega 8: um sobrevivente do SIGTERM que continua vivo (mesma
        # identidade) não perde o direito à escalada manual só porque um poll
        # chegou; um pid reciclado (starttime diferente) cai. Sobreviventes de
        # grupo são podados pelo próprio show_groups, que conhece a família.
        if not self._survivors_from_group:
            self._survivors = [c for c in self._candidates
                               if previous.get(c.pid) == c.starttime]
        self._survivors_from_group = previous_group if self._survivors else False
        self._sync_tree()
        if keep is not None:
            for row, c in enumerate(self._candidates):
                if c.pid == keep:
                    self.select(row)
                    break
        if self._action_blocked():
            self.force_button.setEnabled(False)
            return
        if self._survivors:
            self.status_label.setText(
                f"{len(self._survivors)} processo(s) sobreviveram ao sinal e continuam "
                f"na lista; o Forçar (SIGKILL) é uma decisão manual.")
        elif self._candidates:
            self.status_label.setText(
                f"possivelmente abandonado: {len(self._candidates)} processo(s) com "
                "pai morto, sem CPU e fora da lista protegida — encerrar exige "
                "confirmação.")
        else:
            self.status_label.setText(
                "Sem órfãos: todo processo observado tem pai vivo, consome CPU ou "
                "está na lista protegida.")
        self.force_button.setEnabled(bool(self._survivors) and
                                     self._survivors_sigterm)

    def show_groups(self, groups):
        # a identidade da escolha é lida ANTES de trocar `_groups`: ler depois usava
        # o índice antigo contra a lista nova e derrubava o snapshot inteiro quando
        # o grupo escolhido sumia entre dois polls (R05)
        keep = None
        if self._groups and self._group_index < len(self._groups):
            keep = self._groups[self._group_index].group
        self._groups = tuple(groups)
        if self._survivors_from_group:
            # a família mudou: só continua sobrevivente quem ainda está nela com
            # a mesma identidade (pid + starttime); pid reciclado não herda o Forçar
            living = {(m.pid, m.starttime) for target in self._groups
                      for m in target.members}
            self._survivors = [s for s in self._survivors
                               if (s.pid, s.starttime) in living]
            self.force_button.setEnabled(bool(self._survivors) and
                                         self._survivors_sigterm)
            if not self._survivors:
                self._survivors_from_group = False
                if not self._action_blocked():
                    self.status_label.setText(
                    "o sobrevivente não está mais na lista observada; nada pendente "
                    "de escalada.")
        self.group_picker.blockSignals(True)
        self.group_picker.clear()
        for target in self._groups:
            self.group_picker.addItem(
                f"{target.label} · {len(target.members)} processos · "
                f"{_rss(target.total_rss_kb)}")
        self.group_picker.blockSignals(False)
        if not self._groups:
            if self._survivors_from_group:
                self._survivors = []
                self._survivors_from_group = False
                self.force_button.setEnabled(False)
                if not self._action_blocked():
                    self.status_label.setText(
                    "o sobrevivente não está mais na lista observada; nada pendente "
                    "de escalada.")
            self._group_index = 0
            self.group_picker.setEnabled(False)
            self.group_button.setEnabled(False)
            self.group_button.setText("Encerrar grupo")
            return
        self._group_index = self._kept_index(keep)
        self.group_picker.setEnabled(len(self._groups) > 1)
        self.group_button.setEnabled(not self._action_blocked())
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
            f"Encerrar grupo {target.label}\n{len(target.members)} processos · "
            f"{_rss(target.total_rss_kb)}")
        self.group_button.setToolTip(
            f"{len(target.members)} processos · {_rss(target.total_rss_kb)}")

    def _sync_tree(self):
        """Atualiza por identidade (pid+starttime), sem reconstruir a árvore.

        Um poll igual não deve piscar a seleção nem recriar linhas; um PID
        reciclado é outra identidade e ganha outra linha.
        """
        alive = set()
        for index, candidate in enumerate(self._candidates):
            key = (candidate.pid, candidate.starttime)
            alive.add(key)
            item = self._items.get(key)
            state = f"{candidate.state} · pai {candidate.ppid}"
            if candidate.cpu_frac is not None:
                state += f" · cpu {candidate.cpu_frac:.0f}%"
            values = [str(candidate.pid), candidate.comm, _rss(candidate.rss_kb),
                      f"{candidate.idle_s:.0f} s", state]
            if item is None:
                item = QTreeWidgetItem()
                self._items[key] = item
            for column, text in enumerate(values):
                if item.text(column) != text:
                    item.setText(column, text)
            if self.tree.topLevelItem(index) is not item:
                self.tree.insertTopLevelItem(index, item)
        for key, item in list(self._items.items()):
            if key in alive:
                continue
            position = self.tree.indexOfTopLevelItem(item)
            if position >= 0:
                self.tree.takeTopLevelItem(position)
            del self._items[key]

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
        if self._action_blocked():
            return
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
        if self._action_blocked():
            return
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
        if self._action_blocked():
            return
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

    def _action_blocked(self):
        return self._pending is not None or self._unknown_operation

    def _unknown(self, response):
        self._unknown_operation = True
        self._survivors = []
        self._survivors_sigterm = self._survivors_from_group = False
        self.term_button.setEnabled(False)
        self.group_button.setEnabled(False)
        self.force_button.setEnabled(False)
        self.status_label.setText("resultado desconhecido; não repetir nem forçar: " +
            str(response.get("reason", "")) + " · operação " + str(response.get("operation_id", "")))

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
        if isinstance(results, Future):
            self._pending = results
            self.term_button.setEnabled(False)
            self.group_button.setEnabled(False)
            self.force_button.setEnabled(False)
            self.status_label.setText("execução em filho; aguardando acompanhamento e resultado…")
            timer = QTimer(self)
            timer.setInterval(25)
            def receive():
                if not results.done():
                    return
                timer.stop()
                timer.deleteLater()
                self._pending = None
                response = {}
                try:
                    response = results.result()
                    if not isinstance(response, dict):
                        raise ValueError("resposta do executor ilegível")
                    from ..actions.orphans.reaper import TermResult
                    items = [TermResult(**item) for item in response.get("effects", {}).get("results", ())]
                except Exception as exc:
                    response = {"outcome": "desconhecido", "reason": str(exc),
                                "operation_id": response.get("operation_id", "") if isinstance(response, dict) else ""}
                if response.get("outcome") == "desconhecido":
                    self._unknown(response)
                    return
                self.term_button.setEnabled(True)
                self.group_button.setEnabled(bool(self._groups))
                if not items:
                    self.status_label.setText(str(response.get("reason", "nenhum sinal comprovado")))
                    return
                self._after(items, payload, sigterm=sigterm, from_group=from_group)
            timer.timeout.connect(receive)
            timer.start()
            return
        if not results:
            return
        refused = [r for r in results if not r.ok]
        # entrega 8: o SIGTERM que saiu e o processo que continuou de pé é
        # sobrevivente observado — não pode ficar fora do conjunto do Forçar
        survived = [r for r in results if r.ok and r.exited is False]
        by_pid = {item.pid: item for item in payload}
        pending = refused + survived
        self._survivors = [by_pid[r.pid] for r in pending if r.pid in by_pid]
        self._survivors_from_group = from_group
        self._survivors_sigterm = sigterm
        self.force_button.setEnabled(bool(self._survivors) and sigterm)
        sent = len(results) - len(refused)
        observed = [r for r in results if r.ok and r.exited is not None]
        if survived:
            detail = [f"sinal enviado para {sent} processo(s)",
                      f"{len(survived)} continuam ativos após o sinal"]
            if refused:
                detail.append("recusado: " +
                              " · ".join(r.reason or "" for r in refused))
            self.status_label.setText(
                "; ".join(detail) +
                " — o Forçar (SIGKILL) é uma decisão manual.")
        elif refused and sent:
            # R10: sucesso e recusa na mesma leva são resultado parcial, e o parcial
            # não pode ser lido como "tudo certo" nem esconder quem ficou de fora.
            self.status_label.setText(
                f"sinal enviado para {sent} processo(s); resultado parcial — "
                "recusado: " + " · ".join(r.reason or "" for r in refused))
        elif refused:
            self.status_label.setText(
                "recusado: " + " · ".join(r.reason or "" for r in refused))
        elif observed and len(observed) == len(results):
            # só o acompanhamento autoriza "encerrado": o sinal sair não prova nada
            self.status_label.setText(
                f"encerrado: {len(results)} processo(s) observados fora do /proc.")
        else:
            self.status_label.setText(
                f"sinal enviado: {len(results)} processo(s); a próxima leitura "
                f"confirma o efeito.")

    @staticmethod
    def _ask_dialog(text: str) -> bool:
        answer = QMessageBox.question(
            None, "Fôlego", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes
