"""App bootstrap: python -m folego."""
import sys

from PySide6.QtWidgets import QApplication

from .core.collector import MetricsCollector
from .core.instance import AlreadyRunning, InstanceLock
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def main() -> int:
    lock = InstanceLock()
    try:
        lock.acquire()
    except AlreadyRunning as exc:
        sys.stderr.write(f"folego: {exc}; a instância existente continua no "
                         "controle. Nada foi aberto.\n")
        return 0
    except OSError as exc:
        sys.stderr.write(f"folego: não foi possível garantir instância única: "
                         f"{exc}\n")
        return 1
    try:
        # Menu/Desktop launchers: create if missing, never autostart, never overwrite the user's own.
        from . import shortcuts
        for state in shortcuts.ensure():
            if state.status in {"created", "updated", "failed"}:
                sys.stderr.write(f"folego: atalho {state.location} {state.status}: {state.path} {state.detail}\n")
    except Exception as exc:  # a shortcut problem must never block opening the app
        sys.stderr.write(f"folego: atalhos não verificados: {exc}\n")
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("folego")
        # Wayland app id = desktop file name: the launcher and the KWin widget rule match "folego"
        app.setDesktopFileName("folego")
        apply_theme(app)
        from .actions.accessibility import Supervisor
        win = MainWindow(collector_factory=MetricsCollector, accessibility_factory=Supervisor, startup_defaults=True)
        win.show()
        win.start()
        return app.exec()
    finally:
        lock.release()
