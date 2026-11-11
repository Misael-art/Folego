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

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..actions.disk.planner import fmt_bytes
from ..core.host_guard import GUIDES

PLAN_PENDING = "ainda não analisado — use Reconsultar o disco."
PLAN_LOADING = "consultando o disco (dry-run, nada é escrito)…"
QUARANTINE_PENDING = "quarentena ainda não consultada."
PLAN_ARGV = (sys.executable, "-m", "folego", "disk", "plan", "--json")
# (row key, column title); the last column is the state, derived per row
COLUMNS = (("path", "caminho"), ("size", "tamanho"), ("files", "arquivos"))
QUARANTINE_COLUMNS = (("name", "nome"), ("size", "tamanho"),
                      ("state", "estado"), ("original", "origem"))


class HostHealthPanel(QWidget):
    """Focused host signals. Every button explains a manual next step."""

    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._report = None
        self._thermal = None
        self._power = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        title = QLabel("Saúde do host")
        title.setObjectName("section")
        self.updated = QLabel("Aguardando primeira verificação")
        self.updated.setObjectName("quality")
        self.updated.setTextFormat(Qt.TextFormat.PlainText)
        button = QPushButton("Verificar agora")
        button.setAccessibleName("Verificar novamente a saúde do host")
        button.clicked.connect(self.refresh_requested)
        heading = QVBoxLayout()
        heading.addWidget(title)
        heading.addWidget(self.updated)
        top = QHBoxLayout()
        top.addLayout(heading)
        top.addStretch(1)
        self.copy_button = QPushButton("Copiar dados")
        self.copy_button.setAccessibleName("Copiar diagnóstico da saúde do host")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_diagnostic)
        top.addWidget(self.copy_button)
        top.addWidget(button)
        layout.addLayout(top)

        self.thermal_card = QFrame()
        self.thermal_card.setObjectName("card")
        self.thermal_card.setProperty("level", "ok")
        thermal_layout = QHBoxLayout(self.thermal_card)
        thermal_text = QVBoxLayout()
        self.thermal_title = QLabel("Temperatura aguardando leitura")
        self.thermal_title.setObjectName("section")
        self.thermal_value = QLabel("— °C · origem desconhecida")
        self.thermal_value.setTextFormat(Qt.TextFormat.PlainText)
        self.thermal_detail = QLabel("Sem leitura confiável ainda")
        self.thermal_detail.setWordWrap(True)
        self.thermal_detail.setTextFormat(Qt.TextFormat.PlainText)
        thermal_text.addWidget(self.thermal_title)
        thermal_text.addWidget(self.thermal_value)
        thermal_text.addWidget(self.thermal_detail)
        thermal_layout.addLayout(thermal_text, 1)
        thermal_button = QPushButton("Ver orientação")
        thermal_button.clicked.connect(lambda: self._guide("thermal"))
        thermal_button.setAccessibleName("Ver orientação para calor e carga")
        thermal_layout.addWidget(thermal_button)
        layout.addWidget(self.thermal_card)

        group = QFrame()
        group.setObjectName("card")
        grouped = QVBoxLayout(group)
        grouped.setSpacing(7)
        self.rows = {}
        for index, (key, label) in enumerate((
                ("power", "Alimentação e proteção"),
                ("pressure", "Pressão de CPU e I/O"),
                ("ntfs", "Volumes NTFS"), ("service", "Serviços do usuário"),
                ("btrfs", "Disco Btrfs"), ("reboot", "Reinícios registrados"))):
            if index:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                grouped.addWidget(line)
            text = QVBoxLayout()
            name = QLabel(label)
            name.setObjectName("section")
            value = QLabel("Aguardando leitura")
            value.setWordWrap(True)
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setAccessibleName(f"{label}: aguardando leitura")
            text.addWidget(name)
            text.addWidget(value)
            row = QHBoxLayout()
            row.addLayout(text, 1)
            action = QPushButton("Orientação")
            action.setAccessibleName(f"Ver orientação sobre {label.lower()}")
            action.clicked.connect(lambda checked=False, issue=key: self._guide(issue))
            row.addWidget(action)
            grouped.addLayout(row)
            self.rows[key] = value
        layout.addWidget(group)

    def _guide(self, issue: str):
        title, text = GUIDES[issue]
        context = self._context(issue)
        QMessageBox.information(self, title, (context + "\n\n" if context else "") + text)

    def _context(self, issue: str) -> str:
        report = self._report or {}
        if issue == "service":
            items = report.get("services", {}).get("items", [])
            if items:
                return "Observado: " + ", ".join(item["unit"] for item in items[:3])
        if issue == "ntfs":
            ntfs = report.get("ntfs", {})
            if ntfs.get("count_10m"):
                mount = ntfs.get("mount")
                return f"Observado: {ntfs['count_10m']} avisos em 10 min" + (
                    f"; possível volume {mount['mount']}" if mount else "; volume não atribuído")
        if issue == "btrfs":
            items = [row for row in report.get("btrfs", []) if row.get("quality") == "ok"]
            if items:
                return "Observado: " + ", ".join(
                    f"{row['id']} = {row['counters']['corruption_errs']} erros acumulados"
                    for row in items[:3])
        if issue == "reboot":
            boots = report.get("boots", {})
            if boots.get("items"):
                return "Boots registrados:\n" + "\n".join(
                    f"{row.get('boot_id', 'ID desconhecido')}: {row.get('period', 'período desconhecido')}"
                    + (f" · última amostra: {row['timeline']['last']['at']}"
                       if row.get("timeline", {}).get("last") else
                       " · sem amostra local; estado anterior desconhecido"
                       if row.get("timeline", {}).get("quality") == "missing" else "")
                    for row in boots["items"][:4])
        if issue == "thermal" and self._thermal:
            return (f"Observado: {self._thermal.get('sensor', 'sensor desconhecido')} "
                    f"{self._thermal.get('current_c', '—')} °C agora; "
                    f"pico {self._thermal.get('peak_c', '—')} °C em 4 min")
        return ""

    def copy_diagnostic(self):
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(json.dumps({"host": self._report, "thermal": self._thermal,
                                          "power": self._power},
                                         ensure_ascii=False, indent=2))

    def show_power_status(self, report: dict):
        self._power = report
        self.rows['power'].setText(report['message'])
        self.copy_button.setEnabled(True)

    def show_error(self, message: str):
        self.updated.setText(f"Verificação indisponível: {message[:180]}")
        for value in self.rows.values():
            value.setText("Leitura antiga ou desconhecida; tente verificar novamente")
        self._report = None
        self.copy_button.setEnabled(False)

    def show_report(self, report: dict):
        self._report = report
        self.copy_button.setEnabled(True)
        try:
            seen = datetime.fromisoformat(report["observed_at"])
            updated = seen.strftime("%d/%m %H:%M")
        except (KeyError, TypeError, ValueError):
            updated = "horário desconhecido"
        self.updated.setText("Última verificação: " + updated)
        ntfs = report.get("ntfs", {})
        if ntfs.get("quality") not in ("ok", "partial"):
            ntfs_text = "Avisos NTFS desconhecidos · " + ntfs.get("reason", "fonte indisponível")
        else:
            count = ntfs.get("count_10m", 0)
            mount = ntfs.get("mount")
            target = f" · possível volume {mount['mount']}" if mount else " · volume não atribuído"
            quantity = f"pelo menos {count}" if ntfs.get("quality") == "partial" else str(count)
            ntfs_text = (f"{quantity} {'aviso' if count == 1 else 'avisos'} de metadados nos últimos 10 min" if count else
                         "Nenhum aviso observado nos últimos 10 min (integridade não comprovada)") + target
            affected = ntfs.get("index_inodes_10m")
            if isinstance(affected, int) and affected > 0:
                prefix = "ao menos " if ntfs.get("quality") == "partial" else ""
                label = "índice identificado" if affected == 1 else "índices identificados"
                ntfs_text += f" · {prefix}{affected} {label}"
        self.rows["ntfs"].setText(ntfs_text)

        services = report.get("services", {})
        items = services.get("items", [])
        inventory = services.get("inventory", [])
        if services.get("quality") != "ok":
            service_text = "Leitura parcial ou desconhecida · " + services.get("reason", "")
        elif items:
            first = items[0]
            more = (f" · mais {len(items)-1} {'unit' if len(items) == 2 else 'units'}"
                    if len(items) > 1 else "")
            count = first.get("restarts")
            restarts = (f"{count} {'reinício' if count == 1 else 'reinícios'} na contagem atual do systemd"
                        if isinstance(count, int) else "reinícios desconhecidos")
            service_text = (f"{first['unit']} ({first.get('owner', 'responsável desconhecido')}) · "
                            f"{first.get('state', 'estado desconhecido')} · {restarts}{more}")
        else:
            unknown = sum(item.get("quality") != "ok" for item in inventory)
            service_text = (f"Nenhuma falha ou loop observado · {len(inventory)} units identificadas"
                            + (f" · {unknown} sem leitura confiável" if unknown else ""))
        self.rows["service"].setText(service_text)
        self.rows["service"].setToolTip("\n".join(
            f"{item['unit']} · {item.get('owner', 'responsável desconhecido')} · "
            f"{item.get('state', item.get('reason', 'desconhecido'))} · "
            f"{item.get('enabled', 'habilitação desconhecida')} · "
            f"{item.get('source', 'fonte desconhecida')}"
            for item in inventory))

        disks = report.get("btrfs", [])
        known = [d for d in disks if d.get("quality") == "ok"]
        if known:
            total = sum(d["counters"]["corruption_errs"] for d in known)
            increments = [d["delta"]["corruption_errs"] for d in known if d.get("delta") is not None]
            complete = (len(known) == len(disks) and report.get("btrfs_quality") == "ok"
                        and report.get("baseline_quality") == "ok")
            trend = (f"+{sum(increments)} desde a leitura anterior"
                     if complete and len(increments) == len(known)
                     else "tendência ou cobertura desconhecida")
            recent = sum(d.get("recent_delta", {}).get("corruption_errs", 0)
                         for d in known if isinstance(d.get("recent_delta"), dict))
            if recent > 0:
                trend += (f" · +{recent} {'erro' if recent == 1 else 'erros'} "
                          "de corrupção nas últimas 24 h")
            amount = f"{total:,}".replace(",", ".")
            scope = "" if complete else " observados; demais dispositivos desconhecidos"
            btrfs_text = f"{amount} {'erro acumulado' if total == 1 else 'erros acumulados'} de corrupção{scope} · {trend}"
        elif report.get("btrfs_quality") != "ok" or report.get("baseline_quality") != "ok":
            btrfs_text = "Contadores ou histórico desconhecidos · " + (report.get("btrfs_reason") or report.get("baseline_reason", ""))
        else:
            btrfs_text = "Nenhum volume Btrfs observado nesta consulta"
        self.rows["btrfs"].setText(btrfs_text)

        boots = report.get("boots", {})
        count = len(boots.get("items", []))
        if boots.get("quality") == "unknown":
            boot_text = "Histórico de boot desconhecido · " + boots.get("reason", "")
        else:
            boot_text = f"{count} {'boot' if count == 1 else 'boots'} no journal · " + boots.get("reason", "encerramento anterior desconhecido")
        previous = boots.get("items", [])[-2] if count >= 2 else None
        previous_timeline = previous.get("timeline", {}) if previous else {}
        if previous_timeline.get("last"):
            boot_text += f"\nBoot anterior: última amostra {previous_timeline['last']['at']}"
            if previous.get("sample_to_journal_s") is not None:
                boot_text += (f" · {previous['sample_to_journal_s']:g} s até o último "
                              "registro retido no journal")
                if previous.get("gap_clock") == "wall":
                    boot_text += " (relógio civil; sujeito a ajuste)"
            if previous_timeline.get("quality") != "ok":
                boot_text += " · evidência parcial"
        elif previous_timeline.get("quality") == "missing":
            boot_text += "\nBoot anterior: sem amostra local; estado desconhecido"
        elif previous_timeline.get("quality") == "unknown":
            boot_text += "\nBoot anterior: histórico local ilegível"
        timeline = report.get("timeline", {})
        if timeline.get("quality") in ("ok", "partial") and timeline.get("last_at"):
            try:
                sample_at = datetime.fromisoformat(timeline["last_at"]).strftime("%d/%m %H:%M:%S")
            except (TypeError, ValueError):
                sample_at = "horário desconhecido"
            boot_text += f" · última amostra local: {sample_at}"
        elif timeline.get("quality") == "partial":
            boot_text += " · amostras locais incompletas"
        elif timeline.get("quality") in ("missing", "unknown", "stale"):
            boot_text += " · amostras locais indisponíveis"
        capacity = timeline.get("capacity") or {}
        if capacity.get("near_limit"):
            boot_text += " · histórico perto do limite; gravação pode parar"
        self.rows["reboot"].setText(boot_text)

    def show_thermal(self, thermal: dict):
        self._thermal = thermal
        state = thermal.get("state")
        value = thermal.get("current_c")
        if value is None:
            self.thermal_title.setText("Temperatura desconhecida")
            self.thermal_value.setText("— °C · fonte indisponível")
            self.thermal_detail.setText(thermal.get("reason", "Sem leitura recente"))
            level = "ok"
        else:
            titles = {"critical": "Limite térmico crítico alcançado",
                      "danger": "Limite térmico passivo alcançado",
                      "high": "Calor elevado", "recent_high": "Pico de calor recente"}
            self.thermal_title.setText(titles.get(state, "Temperatura observada"))
            peak = thermal.get("peak_c")
            label = thermal.get("sensor") or "sensor desconhecido"
            self.thermal_value.setText(f"{'ACPI' if label == 'acpitz' else label}: "
                                       f"{value:g} °C agora · pico {peak:g} °C em 4 min")
            limit = thermal.get("passive_c")
            critical = thermal.get("critical_c")
            rpm = thermal.get("fan_rpm")
            top = thermal.get("top_process")
            details = [f"Limite passivo: {limit:g} °C" if limit is not None else
                       "Limite passivo não informado",
                       f"Limite crítico: {critical:g} °C" if critical is not None else
                       "Limite crítico não informado",
                       f"Cooler: {rpm} RPM" if rpm is not None else "RPM indisponível"]
            if top:
                details.append(f"Maior CPU no pico: {top['name']} ({top['cpu_percent_of_core']:g}% de um núcleo); relação não comprovada")
            self.thermal_detail.setText(" · ".join(details))
            level = "danger" if state in ("danger", "critical") else "warning" if state in ("high", "recent_high") else "ok"
        self.thermal_card.setProperty("level", level)
        self.thermal_card.style().unpolish(self.thermal_card)
        self.thermal_card.style().polish(self.thermal_card)
        cpu = thermal.get("pressure_cpu_avg60")
        io = thermal.get("pressure_io_avg60")
        self.rows["pressure"].setText(
            f"PSI em 60 s · CPU {cpu:g}% · I/O {io:g}%" if cpu is not None and io is not None
            else "PSI de CPU ou I/O indisponível; pressão desconhecida")


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
    host_refresh_requested = Signal()

    def __init__(self, *, jobs, confirm_fn=None, parent=None):
        super().__init__(parent)
        self._jobs = jobs
        self._confirm = confirm_fn or self._ask_dialog
        self.rows: list[dict] = []
        self.quarantine_rows: list[dict] = []
        self.thumbnails_kb: int | None = None
        self._last_status = ""
        self._uncertain = False
        self._pending_review_id = ""
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
        q_bar.addStretch(1)

        self.host_health = HostHealthPanel()
        self.host_health.refresh_requested.connect(self.host_refresh_requested.emit)
        plan_title = QLabel("Análise do disco")
        quarantine_title = QLabel("Quarentena reversível")
        for title in (plan_title, quarantine_title):
            title.setObjectName("section")
        self.table.hide()
        self.quarantine_table.hide()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(self.host_health)
        layout.addWidget(plan_title)
        layout.addWidget(self.summary)
        layout.addLayout(bar)
        layout.addWidget(self.table, 2)
        layout.addWidget(quarantine_title)
        layout.addWidget(self.quarantine_summary)
        layout.addLayout(q_bar)
        layout.addWidget(self.quarantine_table, 1)
        layout.addWidget(self.purge_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.status)
        layout.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)

    def show_host_report(self, report: dict):
        self.host_health.show_report(report)

    def show_host_error(self, message: str):
        self.host_health.show_error(message)

    def show_thermal(self, thermal: dict):
        self.host_health.show_thermal(thermal)

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
            self.table.hide()
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
            f"lidos {fmt_bytes(payload.get('scanned_bytes', 0))}" if self.rows
            else "Nenhum item encontrado no escopo analisado.")
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
            self.quarantine_table.hide()
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
            "bytes": int(e.get("bytes") or 0),
            "state": str(e.get("state", "?")),
            "original": str(e.get("original", "—")),
            "stored": e.get("state") == "stored",
        } for e in entries]
        self.quarantine_table.setRowCount(len(self.quarantine_rows))
        self.quarantine_table.setVisible(bool(self.quarantine_rows))
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
        self.table.setVisible(bool(self.rows))
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
        self._jobs.review_and_run("restore", item["entry_id"], title="Restaurar quarentena",
                expected_scope=[{"key": item["entry_id"], "source": item["original"], "bytes": item["bytes"]}],
                confirm_fn=lambda title, text: self._confirm(text), text=
                f"Restaurar {item['original']} a partir da quarentena?\n"
                "O conteúdo volta ao caminho original; a origem precisa estar "
                "livre e não ser substituída.",
                       done=self._mutation_done)

    def purge_selected(self):
        if self._uncertain:
            return
        item = self._selected_quarantine()
        if item is None or not item["stored"]:
            self._status("selecione uma entrada armazenada antes de apagar.")
            return
        self._jobs.review_and_run("purge", item["entry_id"], title="Apagar quarentena (irreversível)",
                expected_scope=[{"key": item["entry_id"], "source": item["original"], "bytes": item["bytes"]}],
                confirm_fn=lambda title, text: self._confirm(text), text=
                f"Apagar de vez {item['original']} ({item['size']})?\n"
                "Esta ação é IRREVERSÍVEL: não haverá restauração. O item só pode "
                "ser apagado se ainda estiver íntegro e dentro do destino de "
                "retenção.",
                       done=self._mutation_done)

    def _mutation_done(self, payload):
        self._quarantine_pending = False
        payload = payload or {}
        if payload.get("outcome") == "cancelamento":
            self._status(payload.get("reason", "cancelado: nenhum efeito solicitado"))
            return
        if not payload or payload.get("outcome") == "desconhecido":
            self._uncertain = True
            self._pending_review_id = payload.get("operation_id") or self._reviewed_operation
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

    def resolve_operation(self, payload):
        key = payload.get("operation_id")
        if key and key == self._pending_review_id:
            self._pending_review_id = ""
            self._uncertain = False
            self._status("verificado: " + str(payload.get("reason") or "resultado consultado"))
            self.refresh()
            self.refresh_quarantine()

    def _status(self, text: str):
        self._last_status = text
        self.status.setText(text)

    @staticmethod
    def _ask_dialog(text: str) -> bool:
        from .confirmation import confirm_text
        return confirm_text("Fôlego — disco", text)
