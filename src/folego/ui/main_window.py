"""Main window: resource, accessibility and session options with bounded workers.

The window owns the poller, the orphan tracker and the three child-process layers
(tunings, the disk plan and the tmpfs plan); every tab receives plain data and
calls back here when the user confirms an act. The Reaper stays lazy and the
tunings tab is never consulted on its own. Resource effects remain manual;
the production entrypoint separately synchronizes the session-start preference.
"""
import os
import subprocess
import time
import json
import sys
from concurrent.futures import Future

from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMainWindow, QStyle, QStyleOptionTab, QStylePainter, QTabBar, QTabWidget

from . import desktop_caps, title_signal
from .compact import CompactWindow
from .dashboard_tab import DashboardTab
from .disk_tab import DiskTab, plan_argv
from .orphans_panel import OrphansPanel
from .tmpfs_tab import TmpfsTab, argv_for
from .tray import Tray
from .tune_jobs import TuneJobs
from .tunings_tab import TuningsTab
from .accessibility_tab import AccessibilityTab
from .options_tab import OptionsTab
from ..core import health
from ..core.exclusions import ExclusionError, ExclusionList
from ..core.orphans import OrphanTracker, active_investigation, group_targets
from ..core.sessions import SessionError, SessionRegistry
from ..orchestration.config import ConfigError, ConfigStore
from ..orchestration.grants import GrantError, GrantStore
from ..orchestration.journal import Journal
from ..orchestration.history import HistoryReader

# tab title -> the attribute the dashboard's "Ir para …" jumps to
TABS = (("central", "dashboard"), ("ajustes", "tunings"),
        ("órfãos", "orphans"), ("disco", "disk"), ("temporários", "tmpfs"), ("acessibilidade", "accessibility"), ("opções", "options"))
JUMPS = {"memoria": "dashboard", "ajustes": "tunings", "orfaos": "orphans",
         "disco": "disk", "tmpfs": "tmpfs", "accessibility": "accessibility"}
DISK_TIMEOUT_MS = 120_000  # the real cache walk took 54,7 s on this Deck (M3 log)
RUNTIME_SIZE_TIMEOUT_MS = 180_000  # inclui a digitação da senha no diálogo do polkit
TMPFS_TIMEOUT_MS = 45_000  # três volumes × o prazo de varredura de 10 s, com folga


class SidebarTabBar(QTabBar):
    """Tabs on the left with horizontal, readable labels (Qt rotates West tabs by default)."""

    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        size.transpose()
        # largura do maior rótulo, altura de um item de menu: compacto e sem rolagem
        size.setWidth(max(size.width(), self.fontMetrics().horizontalAdvance(self.tabText(index)) + 40, 150))
        size.setHeight(max(self.fontMetrics().height() + 28, 40))
        return size

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionTab()
        for index in range(self.count()):
            self.initStyleOption(option, index)
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabShape, option)
            # o rótulo usa o próprio retângulo da aba, desenhado como aba horizontal
            option.shape = QTabBar.Shape.RoundedNorth
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabLabel, option)


class MainWindow(QMainWindow):
    def __init__(self, collector_factory=None,
                 thresholds: title_signal.Thresholds | None = None,
                 *, tracker: OrphanTracker | None = None, reaper_factory=None,
                 confirm_fn=None, jobs=None, disk_jobs=None, tmpfs_jobs=None,
                 sessions: SessionRegistry | None = None,
                 exclusions: ExclusionList | None = None, journal=None,
                 config_store=None, grant_store=None, compact_factory=None, process_jobs=None,
                 accessibility_factory=None, startup_defaults=False):
        super().__init__()
        self._thresholds = thresholds or title_signal.Thresholds()
        self._journal = journal or Journal()
        self._history_reader = HistoryReader(self._journal)
        self._history_poller = None
        self._history_text = "aguardando leitura do histórico"
        self._config_store = config_store or ConfigStore()
        self._grant_store = grant_store or GrantStore()
        self._health = health.HealthEngine(thresholds=self._thresholds)
        self.setWindowTitle("Fôlego · aguardando primeira leitura")
        self.resize(900, 620)
        self._sessions = sessions or SessionRegistry()
        self._exclusions = exclusions or ExclusionList()
        self._protect_ready = False
        self._protect_default = None
        self._protect_sessions: dict[tuple[int, int], str] = {}
        self._protect_projects: dict[tuple[int, int], str] = {}
        self._protect_session_ids: dict[tuple[int, int], str] = {}
        self._protect_exclusions = ()
        self._sessions_view = ()
        self._exclusions_view = ()
        self._tracker = tracker or OrphanTracker(
            protected_fn=self._protection_reason)
        self._reaper_factory = reaper_factory
        self._reaper = None
        self._collector_factory = collector_factory
        self._poller = None
        self._quitting = False
        self._tray_note = ""
        self._compact = None
        self._compact_factory = compact_factory or (
            lambda view, caps: CompactWindow(view, caps=caps))
        self._automation_view = {}
        self._caps = None
        self._paused = False
        self._last_snapshot = None
        self._last_signal = None
        self._collection_error = ""
        self._jobs = jobs if jobs is not None else TuneJobs(parent=self)
        self._disk_jobs = disk_jobs if disk_jobs is not None else TuneJobs(
            parent=self, argv_factory=plan_argv, timeout_ms=DISK_TIMEOUT_MS)
        self._tmpfs_jobs = tmpfs_jobs if tmpfs_jobs is not None else TuneJobs(
            parent=self, argv_factory=argv_for, timeout_ms=TMPFS_TIMEOUT_MS)
        self._process_jobs = process_jobs if process_jobs is not None else TuneJobs(
            parent=self, argv_factory=process_argv, timeout_ms=20_000)
        self._process_group = ""

        self.dashboard = DashboardTab(on_jump=self.jump_to, thresholds=self._thresholds,
                                      on_widget=self.enter_widget_mode)
        self._widget_confirm = confirm_fn or self._ask_widget_rule
        self._show_automation_state()
        self.tunings = TuningsTab(jobs=self._jobs, confirm_fn=confirm_fn)
        self.orphans = OrphansPanel(confirm_fn=confirm_fn,
                                    on_terminate=self._terminate,
                                    on_force=self._force,
                                    on_group=self._group)
        self.disk = DiskTab(jobs=self._disk_jobs, confirm_fn=confirm_fn)
        # a autenticação do polkit pode levar minutos; não herda o prazo de varredura
        self._runtime_jobs = TuneJobs(parent=self, argv_factory=argv_for, timeout_ms=RUNTIME_SIZE_TIMEOUT_MS)
        self.tmpfs = TmpfsTab(jobs=self._tmpfs_jobs, confirm_fn=confirm_fn, runtime_jobs=self._runtime_jobs)
        self._accessibility_factory = accessibility_factory
        self.accessibility = AccessibilityTab(inspect_fn=accessibility_factory().inspect if accessibility_factory else None,
                                               confirm_fn=confirm_fn)
        self.accessibility.report_ready.connect(self._show_accessibility)
        self.options = OptionsTab()
        self.options.operation_verified.connect(self._operation_verified)
        self._startup_defaults = startup_defaults

        self.tabs = QTabWidget()
        self.tabs.setTabBar(SidebarTabBar())
        # navegação lateral, como no padrão de painéis de manutenção; os títulos continuam os mesmos
        self.tabs.setObjectName("sidebar")
        self.tabs.setTabPosition(QTabWidget.TabPosition.West)
        for title, attribute in TABS:
            self.tabs.addTab(getattr(self, attribute), title)
        self.setCentralWidget(self.tabs)
        self.accessibility.options_requested.connect(self._open_options)

        self.tray = Tray(self, thresholds=self._thresholds)
        # atalhos locais da aplicação (não dependem de portal global do Wayland)
        self._compact_shortcut = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        self._compact_shortcut.activated.connect(self.show_compact)
        self._pause_shortcut = QShortcut(QKeySequence("Ctrl+Shift+P"), self)
        self._pause_shortcut.activated.connect(self.toggle_pause)
        self._freshness_timer = QTimer(self)
        self._freshness_timer.setInterval(1000)
        self._freshness_timer.timeout.connect(self._refresh_freshness)
        self._freshness_timer.start()

    # -------------------------------------------------------------------- polling

    def start(self):
        if self._startup_defaults:
            self.options.start(sync=True)
            self._startup_defaults = False
        self._request_history()
        if self._accessibility_factory:
            self.accessibility.start()
        if self._collector_factory is None or self._poller is not None:
            return
        if not self.tray.install():
            self._tray_note = self.tray.fallback
        self._caps = desktop_caps.detect(
            session_type=os.environ.get("XDG_SESSION_TYPE"),
            platform=QGuiApplication.platformName(),
            tray=self.tray.tray is not None)
        from .workers import Poller
        collector = self._collector_factory()
        collect_fn = getattr(collector, "collect", None) or collector
        self._poller = Poller(collect_fn=collect_fn, offload=True)
        self._poller.snapshot_ready.connect(self.apply_snapshot)
        self._poller.error.connect(self.show_error)
        self._poller.start()

    def _show_accessibility(self, report):
        words = {"observed": "configuração observada", "degraded": "revisão necessária",
                 "waiting": "aguardando responsável", "unknown": "desconhecida"}
        detail = "; ".join(report.get("blockers", []))
        self.dashboard.input_status.setText("Entrada: " + words.get(report.get("state"), "desconhecida")
                                           + (" · " + detail if detail else " · funcionamento físico não testado"))
        self.tray.show_accessibility(report)

    def _open_options(self):
        self.tabs.setCurrentWidget(self.options)
        self.options.start()

    def _operation_verified(self, payload):
        if payload.get("outcome") not in ("sucesso", "recusa", "cancelamento"):
            return
        for panel in (self.tunings, self.tmpfs, self.disk):
            panel.resolve_operation(payload)
        if payload.get("operation_id") == self.accessibility._pending:
            self.accessibility.completed(payload)

    def _show_automation_state(self) -> None:
        """Read-only F6 state; no control here can create or widen a grant."""
        try:
            config = self._config_store.read()
            grants = self._grant_store.for_action("tmpfs.release")
        except (ConfigError, GrantError) as exc:
            self._apply_automation_view(
                mode="desconhecido", preset="desconhecido", paused=True,
                active_grants=0, error=str(exc))
            return
        self._apply_automation_view(
            mode=config.mode, preset=config.preset, paused=config.paused,
            active_grants=len(grants))

    def _apply_automation_view(self, *, mode: str, preset: str, paused: bool,
                               active_grants: int, error: str = "") -> None:
        self._automation_view = {
            "mode": mode, "preset": preset, "paused": paused,
            "active_grants": active_grants, "error": error,
        }
        self.dashboard.show_automation(
            mode=mode, preset=preset, paused=paused,
            active_grants=active_grants, error=error)
        if self._compact is not None:
            self._compact.set_automation(
                mode=mode, preset=preset, active_grants=active_grants,
                error=error)

    def show_error(self, message: str):
        self._collection_error = message
        self.dashboard.status.setText(f"⚠ última falha de coleta: {message}")
        self._refresh_freshness()

    def _refresh_freshness(self, now_mono=None):
        """Invalidate old health without collecting or reading the journal.

        This timer never counts a repeated sample towards recovery hysteresis.
        Only a new snapshot can restore the health indicator.
        """
        snapshot = self._last_snapshot
        if snapshot is None and not (self._paused or self._collection_error):
            return
        now = time.monotonic() if now_mono is None else now_mono
        if self._paused or self._collection_error:
            reason = ("monitoramento pausado; saúde não comprovada" if self._paused
                      else f"falha de coleta: {self._collection_error}")
            signal = title_signal.TitleSignal("unknown", "⚪", f"Fôlego ⚪ · {reason}")
        elif snapshot.mono > 0 and snapshot.age_s(now) > self._thresholds.stale_after_s:
            signal = title_signal.compute(snapshot, self._thresholds, now_mono=now)
        else:
            return
        if self._last_signal is not None and signal.text == self._last_signal.text:
            return
        self._last_signal = signal
        self.setWindowTitle(signal.text)
        self.dashboard.invalidate_health(signal)
        if self.tray.tray is not None and snapshot is not None:
            self.tray.show_snapshot(snapshot, signal=signal)
        if self._compact is not None and snapshot is not None:
            self._compact.show_snapshot(snapshot, signal=signal)
        elif self._compact is not None:
            self._compact.signal_label.setText(signal.text)
            self._compact.detail_label.setText("aguardando primeira amostra")

    def apply_snapshot(self, snapshot):
        self._request_history()
        self._collection_error = ""
        signal = title_signal.compute(snapshot, self._thresholds,
                                      engine=self._health)
        self._last_snapshot = snapshot
        self._last_signal = signal
        self.setWindowTitle(signal.text)
        # Uma leitura só das sessões/exclusões por amostra: os predicados são
        # chamados para cada processo e não podem reler o JSON a cada linha.
        self._build_protection()
        candidates = self._tracker.observe(snapshot)
        self.orphans.show_candidates(candidates)
        self.orphans.show_groups(group_targets(
            snapshot.procs, protected_fn=self._protection_reason))
        self.orphans.show_investigation(active_investigation(
            snapshot, protected_fn=self._protection_reason))
        self.orphans.show_protections(self._sessions_view, self._exclusions_view,
                                      error=self._protect_default or "")
        notes = (self._tray_note,) if self._tray_note else ()
        self.dashboard.show_snapshot(
            snapshot, orphan_count=len(candidates),
            thumbnails_kb=self.disk.thumbnails_kb, extra_notes=notes,
            signal=signal, last_operation=self._last_operation_text())
        self.tmpfs.show_volumes(snapshot.tmpfs, ts=snapshot.ts)
        if self.tray.tray is not None:
            self.tray.show_snapshot(snapshot, signal=signal)
        if self._compact is not None:
            self._compact.show_snapshot(snapshot, signal=signal)
            self._compact.set_operation(self._last_operation_text())
            self._compact.set_paused(self._paused)

        if self._paused:
            self._refresh_freshness()

    def _last_operation_text(self) -> str:
        """Only cached text: widget updates never open or parse the journal."""
        return self._history_text

    def _request_history(self):
        if self._history_poller is None:
            from .workers import Poller
            self._history_poller = Poller(self._history_reader.refresh, offload=True,
                                          parent=self, interval_s=2.0)
            self._history_poller.snapshot_ready.connect(self._apply_history)
            self._history_poller.error.connect(self._history_error)
            self._history_poller.start()
        self._history_poller.request()

    def _history_error(self, message):
        self._apply_history(f"histórico ilegível ({message}) — mutações não comprovadas")

    def _apply_history(self, text):
        self._history_text = text
        self.dashboard.last_operation.setText(text)
        if self._compact is not None:
            self._compact.set_operation(text)

    # ---------------------------------------------------------------- protection

    def _build_protection(self):
        """Carrega sessões/exclusões uma vez por amostra; falha fechado."""
        self._protect_sessions = {}
        self._protect_projects = {}
        self._protect_session_ids = {}
        self._protect_exclusions = ()
        self._protect_default = None
        self._protect_ready = True
        self._sessions_view = ()
        self._exclusions_view = ()
        try:
            sessions = self._sessions.snapshot()
        except SessionError as exc:
            self._protect_default = f"registro de sessões ilegível: {exc}"
            return
        self._sessions_view = tuple(sessions)
        for session in sessions:
            key = (session.pid, session.starttime)
            if session.ended:
                continue
            self._protect_session_ids[key] = session.session_id
            if session.keep_active:
                self._protect_sessions[key] = (
                    f"sessão {session.session_id} marcada como manter ativo "
                    f"({session.state})")
            if session.project:
                self._protect_projects[key] = session.project
        try:
            self._protect_exclusions = tuple(self._exclusions.list())
            self._exclusions_view = self._protect_exclusions
        except ExclusionError as exc:
            self._protect_default = f"exclusões ilegíveis: {exc}"

    def _protection_reason(self, proc):
        if not self._protect_ready:
            self._build_protection()
        if self._protect_default:
            return self._protect_default
        key = (proc.pid, proc.starttime)
        reason = self._protect_sessions.get(key)
        if reason:
            return reason
        session_id = self._protect_session_ids.get(key, "")
        project = self._protect_projects.get(key, "")
        for item in self._protect_exclusions:
            if ExclusionList._match(item, proc, project, session_id):
                suffix = " (manter ativo)" if item.keep_active else ""
                return f"exclusão {item.kind}:{item.value}{suffix}"
        return None

    # ------------------------------------------------------- navigation and lifetime

    def jump_to(self, target: str):
        attribute = JUMPS.get(target)
        if attribute is not None:
            self.tabs.setCurrentWidget(getattr(self, attribute))

    def raise_to_user(self):
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def show_compact(self):
        self._request_history()
        if self._compact is None:
            caps = self._caps or desktop_caps.detect(
                session_type=os.environ.get("XDG_SESSION_TYPE"),
                platform=QGuiApplication.platformName(),
                tray=self.tray.tray is not None)
            self._compact = self._compact_factory(self, caps)
        view = self._automation_view
        if view:
            self._compact.set_automation(
                mode=view["mode"], preset=view["preset"],
                active_grants=view["active_grants"], error=view["error"])
        self._compact.set_operation(self._last_operation_text())
        self._compact.set_paused(self._paused)
        if self._last_snapshot is not None:
            self._compact.show_snapshot(self._last_snapshot,
                                        signal=self._last_signal)
        self._compact.show_compact()

    def enter_widget_mode(self) -> bool:
        """Modo widget: abre o widget flutuante e recolhe a janela central para a bandeja."""
        self.show_compact()
        self._offer_kwin_rule()
        return self.hide_window()

    def _offer_kwin_rule(self) -> None:
        """No Wayland do Plasma, só uma regra do KWin mantém o widget por cima; pergunta uma vez."""
        from . import kwin_rule
        caps = self._caps or desktop_caps.detect(session_type=os.environ.get("XDG_SESSION_TYPE"),
                                                 platform=QGuiApplication.platformName())
        if caps.keep_above or "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            return
        settings = self._widget_settings()
        if settings.value("widget/kwin_rule_declined", False) in (True, "true"):
            return
        try:
            if kwin_rule.installed():
                return
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            self._tray_note = f"regras do KWin indisponíveis: {exc}"
            return
        if not self._widget_confirm(
                "Manter o widget em primeiro plano",
                "No Plasma com Wayland, um aplicativo não pode se manter sobre as outras janelas sozinho. "
                "Posso criar uma regra do KWin só para o widget do Fôlego: fica acima das janelas, sem "
                "borda, fora da barra de tarefas e do Alt+Tab, nunca recebe o foco e abre no canto inferior "
                "direito. Outras regras não são alteradas e esta pode ser removida com "
                "`folego widget-rule --remover`."):
            settings.setValue("widget/kwin_rule_declined", True)
            return
        screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        compact = self._compact
        x = (area.x() + area.width() - compact.width() - 24) if area else 0
        y = (area.y() + area.height() - compact.sizeHint().height() - 24) if area else 0
        try:
            kwin_rule.install(compact.windowTitle(), x, y, confirmed=True)
        except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
            self._tray_note = f"regra do KWin não criada: {exc}"
            return
        # a regra vale no mapeamento da janela: reabre o widget para aplicá-la já
        compact.hide()
        compact.show_compact()

    def _widget_settings(self):
        from PySide6.QtCore import QSettings
        return QSettings("folego", "folego")

    def _ask_widget_rule(self, title: str, text: str) -> bool:
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def hide_window(self) -> bool:
        """Hide, never stop: a way back must exist (tray or compact control)."""
        if self.tray.tray is None and (self._compact is None or not self._compact.isVisible()):
            self._tray_note = ("bandeja indisponível e controle compacto fechado: "
                              "a janela não será ocultada sem um caminho de volta")
            return False
        self.hide()
        return True

    def pause_watching(self):
        if self._paused:
            return
        self._paused = True
        if self._poller is not None:
            self._poller.pause()
        if self._compact is not None:
            self._compact.set_paused(True)
        self.tray.set_paused(True)
        self._refresh_freshness()

    def resume_watching(self):
        if not self._paused:
            return
        self._paused = False
        if self._poller is not None:
            self._poller.resume()
        if self._compact is not None:
            self._compact.set_paused(False)
        self.tray.set_paused(False)

    def toggle_pause(self) -> bool:
        if self._paused:
            self.resume_watching()
        else:
            self.pause_watching()
        return self._paused

    @property
    def paused(self) -> bool:
        return self._paused

    def quit(self):
        """The tray menu's way out: stop watching, take the children down."""
        self._quitting = True
        if self._compact is not None:
            self._compact.force_close()
        set_visible = getattr(self.tray.tray, "setVisible", None)
        if set_visible is not None:
            set_visible(False)
        self.close()

    # ----------------------------------------------------------------------- acts

    def _reaper_or_new(self):
        if self._reaper is None:
            if self._reaper_factory is None:
                from ..core.process_protection import ProcessProtection
                self._reaper = _default_reaper(ProcessProtection())
            else:
                self._reaper = self._reaper_factory()
        return self._reaper

    def _terminate(self, candidates):
        if self._reaper_factory is None:
            return self._queue_process(candidates)
        reaper = self._reaper_or_new()
        return [reaper.terminate(c) for c in candidates]

    def _force(self, candidates, confirm=False, require_orphan=True):
        if not confirm:
            result = Future()
            result.set_result({"outcome": "recusa", "reason": "SIGKILL exige confirmação separada"})
            return result
        if self._reaper_factory is None:
            return self._queue_process(candidates, force=True, require_orphan=require_orphan,
                                       group=self._process_group if not require_orphan else "")
        reaper = self._reaper_or_new()
        return [reaper.force(c, confirm=confirm, require_orphan=require_orphan)
                for c in candidates]

    def _group(self, target, confirm=False):
        if not confirm:
            result = Future()
            result.set_result({"outcome": "recusa", "reason": "encerramento de grupo exige confirmação"})
            return result
        self._process_group = target.group
        if self._reaper_factory is None:
            return self._queue_process(target.members, require_orphan=False, group=target.group)
        return self._reaper_or_new().terminate_group(target)

    def _queue_process(self, targets, *, force=False, require_orphan=True, group=""):
        from ..actions.orphans.coordinated import plan_for
        if (self._last_snapshot is None or not self._last_snapshot.boot_id or self._paused
                or self._collection_error or self._last_snapshot.is_stale(15.0)):
            result = Future()
            result.set_result({"outcome": "recusa", "reason": "análise de processos antiga/pausada ou boot desconhecido; reanalise"})
            return result
        boot = self._last_snapshot.boot_id
        plan = plan_for(targets, boot_id=boot, force=force, require_orphan=require_orphan, group=group)
        future = Future()
        def complete(payload):
            if payload.get("operation_id") not in (None, plan.operation_id):
                payload = {"outcome": "desconhecido", "reason": "ID do filho difere do plano; consulte a operação"}
            future.set_result({**payload, "operation_id": plan.operation_id})
        self._process_jobs.run("signal", json.dumps(plan.to_dict()), confirm=True, done=complete)
        return future

    def closeEvent(self, event):
        if (not self._quitting and self.tray.tray is None and self._compact is not None
                and self._compact.isVisible()):
            event.ignore()
            self.hide()
            return
        if self._quitting or self.tray.tray is None:
            self._freshness_timer.stop()
            if self._poller is not None:
                self._poller.stop()
            if self._history_poller is not None:
                self._history_poller.stop()
            self._jobs.shutdown()
            self._disk_jobs.shutdown()
            self._tmpfs_jobs.shutdown()
            self._process_jobs.shutdown()
            self.accessibility.stop()
            self.options.stop()
            super().closeEvent(event)
            return
        # a live icon means the signal is resident: hide the window, keep watching
        event.ignore()
        self.hide()


def _default_reaper(protected_fn=None):
    from ..actions.orphans.reaper import Reaper
    from ..safely.audit import AuditLog
    # a GUI não pode congelar: meio segundo cobre a saída normal do SIGTERM; o
    # que não sair nesse prazo é nomeado sobrevivente e o Forçar é decisão manual
    return Reaper(audit=AuditLog(), follow_up_s=0.5, protected_fn=protected_fn)


def process_argv(action, serialized, confirm):
    from ..orchestration.models import ActionPlan
    plan = ActionPlan.from_dict(json.loads(serialized))
    argv = [sys.executable, "-m", "folego", "process", "--plan", serialized, "--json"]
    if confirm:
        argv.append("--confirmar")
        if plan.params["signal"] == 9:
            argv.append("--forcar")
    return argv
