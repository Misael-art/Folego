"""App bootstrap: python -m deck_wellness."""
import sys

from PySide6.QtWidgets import QApplication

from .core.collector import MetricsCollector
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("deck-wellness")
    win = MainWindow(collector_factory=MetricsCollector)
    win.show()
    win.start()
    return app.exec()
