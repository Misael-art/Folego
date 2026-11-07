"""M3 tray: the title-bar signal outside the window, when the session allows it.

Plasma on BigLinux can hide status-notifier items by policy and Wayland gives no
way to prove an icon is actually painted. So the tray is optional by design:
``install()`` reports whether the area exists, and when it does not the app says
where the user still sees the signal (window + title) instead of pretending an
icon is there. Nothing in this class writes: the menu only brings the window up
or stops the watcher — an act on the system needs a click inside the window.
"""
from PySide6.QtGui import QAction
import time
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from . import title_signal


def area_available() -> bool:
    return QSystemTrayIcon.isSystemTrayAvailable()


def _default_tray(parent):
    return QSystemTrayIcon(parent)


class Tray:
    def __init__(self, window, *, available_fn=area_available, tray_factory=None,
                 thresholds: title_signal.Thresholds | None = None):
        self._window = window
        self._available = available_fn
        self._factory = tray_factory or _default_tray
        self._thresholds = thresholds or title_signal.Thresholds()
        self.tray = None
        self.fallback = ""
        self._context_menu = None
        self._pause_action = None
        self._input_note = ""
        self._input_alert = ("", 0)
        self._thermal_alert = (0, 0.0)

    # ------------------------------------------------------------------ lifecycle

    def install(self) -> bool:
        if self.tray is not None:
            return True
        if not self._available():
            self.fallback = ("bandeja indisponível nesta sessão — o sinal fica na "
                             "janela: emoji e números no título da janela")
            return False

        tray = self._factory(self._window)
        tray.setIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        tray.setContextMenu(self._menu())
        tray.activated.connect(self._on_activated)
        self.tray = tray
        tray.setToolTip("Fôlego · aguardando primeira leitura")
        tray.show()
        return True

    def _menu(self):
        # parentless on purpose: the window here is only duck-typed, and the Tray
        # itself keeps the menu alive (a tray does not take ownership of it)
        menu = QMenu()
        open_action = QAction("Abrir Fôlego", menu)
        open_action.triggered.connect(self._window.raise_to_user)
        menu.addAction(open_action)
        for text, method in (("Mostrar controle compacto", "show_compact"),
                             ("Ocultar janela", "hide_window"),
                             ("Pausar monitoramento", "toggle_pause")):
            callback = getattr(self._window, method, None)
            if callback is None:
                continue
            action = QAction(text, menu)
            action.triggered.connect(callback)
            menu.addAction(action)
            if method == "toggle_pause":
                self._pause_action = action
        quit_action = QAction("Sair do Fôlego", menu)
        quit_action.triggered.connect(self._window.quit)
        menu.addAction(quit_action)
        self._context_menu = menu
        return menu

    def set_paused(self, paused: bool):
        """Pause is not quit: the icon stays and the menu says how to resume."""
        action = self._pause_action
        if action is not None:
            action.setText("Retomar monitoramento" if paused
                           else "Pausar monitoramento")

    def _on_activated(self, _trigger=None):
        self.activated()

    # --------------------------------------------------------------------- reading

    def activated(self):
        """Icon clicked: bring the window. An act needs a click inside the window."""
        self._window.raise_to_user()

    def show_snapshot(self, snapshot, *, signal=None):
        if self.tray is None:
            return
        signal = signal or title_signal.compute(snapshot, self._thresholds)
        self.tray.setToolTip(self._tooltip(signal, snapshot))
        self.tray.show()

    def _tooltip(self, signal, snapshot) -> str:
        lines = [signal.text]
        if snapshot.cpu_busy_frac is not None:
            lines.append(f"cpu {snapshot.cpu_busy_frac * 100:.0f}% de "
                         f"{snapshot.cpu_count} cpu(s)")
        if snapshot.zram is not None:
            lines.append(f"zram usado {title_signal.fmt1(snapshot.zram.mem_used_total_kb / title_signal.KB)} MB")
        if not snapshot.swap_known:
            lines.append("zram/swap: inventário desconhecido")
        elif snapshot.swap_total_kb:
            lines.append(
                f"zram/swap {title_signal.fmt1(snapshot.swap_used_kb / title_signal.MB)} GB de "
                f"{title_signal.fmt1(snapshot.swap_total_kb / title_signal.MB)} GB")
        if snapshot.pressure_memory:
            lines.append("psi/memória avg10 "
                         f"{title_signal.fmt1(snapshot.pressure_memory.some_avg10)}")
            if snapshot.pressure_memory.full_avg10 is not None:
                lines.append("psi/full avg10 "
                             f"{title_signal.fmt1(snapshot.pressure_memory.full_avg10)}")
        if snapshot.ts_iso:
            lines.append(f"amostra {snapshot.ts_iso}")
        if self._input_note:
            lines.append(self._input_note)
        return "\n".join(lines)

    def show_accessibility(self, report):
        alerts = report.get("alerts", [])
        note = "; ".join(alerts)[:512] if alerts else ""
        self._input_note = "Entrada: " + note if note else ""
        previous, when = self._input_alert
        now = time.monotonic()
        notify = getattr(self.tray, "showMessage", None)
        if note and notify and (note != previous or now - when >= 300):
            notify("Fôlego · entrada precisa de atenção", note)
            self._input_alert = (note, now)

    def show_thermal(self, thermal: dict):
        """Notify on fresh measured heat, with escalation and bounded repetition."""
        rank = {"high": 1, "danger": 2, "critical": 3}.get(thermal.get("state"), 0)
        notify = getattr(self.tray, "showMessage", None)
        value = thermal.get("current_c")
        if not rank or value is None or notify is None:
            return
        previous, when = self._thermal_alert
        now = time.monotonic()
        interval = 300 if rank == 1 else 60
        if rank <= previous and now - when < interval:
            return
        title = {1: "Fôlego · temperatura elevada",
                 2: "Fôlego · reduza a carga agora",
                 3: "Fôlego · limite térmico crítico"}[rank]
        sensor = "ACPI" if thermal.get("sensor") == "acpitz" else thermal.get("sensor") or "Sensor"
        action = ("Salve o trabalho e peça aos agentes que reduzam a carga."
                  if rank >= 2 else "Revise as tarefas pesadas antes que o calor aumente.")
        notify(title, f"{sensor}: {value:g} °C. {action}")
        self._thermal_alert = (rank, now)

    def show_pressure_alert(self, alert: dict):
        """One bounded warning prepared from fresh, sustained PSI samples."""
        notify = getattr(self.tray, "showMessage", None)
        if notify is None:
            return
        labels = {"memory": "memória", "io": "disco/I/O", "cpu": "CPU"}
        value = alert.get("value")
        if value is None:
            return
        age = alert.get("age_s")
        age_text = f", há {age:g} s" if age is not None else ""
        readings = [alert, *alert.get("also", ())]
        detail = "; ".join(f"{labels.get(item.get('kind'), 'recursos')} "
                           f"{item['value']:g}%" for item in readings)
        notify("Fôlego · pressão sustentada",
               f"PSI de espera em 60 s: {detail} "
               f"(amostra {alert.get('sample_at') or 'sem horário'}{age_text}). "
               "Salve o trabalho e reduza tarefas pelo aplicativo responsável.")
