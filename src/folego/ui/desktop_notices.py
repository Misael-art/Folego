"""Submit bounded notifications asynchronously to the session's native server."""
from collections import deque
import os
import shutil

from PySide6.QtCore import QObject, QProcess, QTimer
from PySide6.QtGui import QGuiApplication


class DesktopNotices(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self._pending = deque(maxlen=16)
        self._process = QProcess(self)
        self._process.setStandardOutputFile(os.devnull)
        self._process.setStandardErrorFile(os.devnull)
        self._process.finished.connect(self._advance)
        self._process.errorOccurred.connect(self._process_error)
        self._timeout = QTimer(self, singleShot=True, interval=4500)
        self._timeout.timeout.connect(self._process.kill)

    def send(self, notice):
        if QGuiApplication.platformName() in ('', 'offscreen', 'minimal'):
            return False
        binary = shutil.which('notify-send')
        if not binary or len(self._pending) >= self._pending.maxlen:
            return False
        self._pending.append((binary, notice.arguments()))
        self._advance()
        return True

    def _advance(self, *_args):
        if self._process.state() != QProcess.ProcessState.NotRunning:
            return
        self._timeout.stop()
        if self._pending:
            binary, arguments = self._pending.popleft()
            self._timeout.start()
            self._process.start(binary, arguments)

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            QTimer.singleShot(0, self, self._advance)

    def close(self):
        self._pending.clear()
        self._timeout.stop()
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
