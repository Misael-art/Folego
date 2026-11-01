"""Quit from the floating widget must stop the actual Qt event loop."""
import json
import subprocess
import sys
import textwrap


def test_quit_from_widget_exits_even_when_the_central_is_hidden():
    script = textwrap.dedent('''
        import json
        from PySide6.QtCore import QTimer, QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
        from folego.ui.main_window import MainWindow
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        win = MainWindow(startup_defaults=False)
        state = dict(watchdog=False)
        def start():
            win.show_compact()
            win.hide()
            QTimer.singleShot(20, win._compact.quit_button.click)
        def watchdog():
            state['watchdog'] = True
            app.exit(10)
        QTimer.singleShot(0, start)
        QTimer.singleShot(2000, watchdog)
        code = app.exec()
        win.quit()
        for window in list(app.topLevelWidgets()): window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        print(json.dumps(dict(state, code=code)))
    ''')
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout.splitlines()[-1])
    assert observed == dict(watchdog=False, code=0)
