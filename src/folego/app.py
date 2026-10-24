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
        app = QApplication(sys.argv)
        app.setApplicationName("folego")
        apply_theme(app)
        win = MainWindow(collector_factory=MetricsCollector)
        win.show()
        win.start()
        return app.exec()
    finally:
        lock.release()
