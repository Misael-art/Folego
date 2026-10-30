import threading
import time

from PySide6.QtCore import QTimer

from folego.ui.main_window import MainWindow
from test_ui_main_window_tabs import snap


def test_slow_history_never_runs_on_gui_thread_or_builds_a_queue(qapp, fake_home):
    entered, release = threading.Event(), threading.Event()
    calls, ticks = [], []
    main_thread = threading.get_ident()
    class SlowHistory:
        def load(self):
            calls.append(threading.get_ident())
            entered.set()
            assert release.wait(3)
            return [], ["fixture corrupta"]
    win = MainWindow(journal=SlowHistory())
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    try:
        win.apply_snapshot(snap())
        assert entered.wait(1)
        deadline = time.monotonic() + .15
        while time.monotonic() < deadline:
            win.apply_snapshot(snap())
            win._last_operation_text()
            qapp.processEvents()
            time.sleep(.005)
        assert len(calls) == 1 and calls[0] != main_thread
        assert len(ticks) >= 3
        assert win._history_poller._requests.qsize() <= 1
        release.set()
        deadline = time.monotonic() + 2
        while "fixture corrupta" not in win._history_text and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(.005)
        assert "fixture corrupta" in win.dashboard.last_operation.text()
    finally:
        release.set()
        timer.stop()
        win.close()
