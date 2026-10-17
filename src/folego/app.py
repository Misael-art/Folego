"""App bootstrap: python -m folego."""
import sys

from PySide6.QtWidgets import QApplication

from .core.collector import MetricsCollector
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("folego")
    win = MainWindow(collector_factory=MetricsCollector)
    win.show()
    win.start()
    return app.exec()
