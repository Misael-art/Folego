"""Bounded audio queue shared by the AI monitor and the options preview."""
from collections import deque
from PySide6.QtCore import QObject, Signal

from ..core.ai_alerts import AlertTracker, TONES
from ..adapters.notification_audio import NotificationAudio
from .desktop_shortcuts import DesktopController
from .desktop_preferences import enabled, SOUNDS, RAISE_VOLUME


class AlertSounds(QObject):
    feedback = Signal(str)
    deliveries_observed = Signal(object)

    def __init__(self, parent=None, *, controller=None):
        super().__init__(parent)
        self.tracker = AlertTracker()
        self.pending = deque()
        self.closed = False
        self.controller = controller or DesktopController(self, backend=NotificationAudio())
        self.controller.feedback.connect(self.feedback)
        self.controller.busy_changed.connect(self._busy)

    def start(self):
        if self.controller.future is None and not self.closed: self.controller.request('alert-recover')

    def observe(self, kind, rows):
        try:
            changes = (self.tracker.quota_changes(rows) if kind == 'quotas' else self.tracker.delivery_changes(rows))
            if kind == 'deliveries' and changes:
                self.deliveries_observed.emit(changes)
            if not enabled(SOUNDS): return
            for tone in changes: self._enqueue(tone)
        except (ValueError, RuntimeError) as exc: self.feedback.emit(str(exc))

    def preview(self, tone):
        if tone in TONES: self._enqueue(tone, preview=True)

    def battery_cue(self, tone):
        if tone in TONES and enabled(SOUNDS): self._enqueue(tone)

    def _enqueue(self, tone, preview=False):
        if self.closed or any(t == tone for t, _ in self.pending): return
        # At most one pending instance per known cue. Coincident accounts
        # coalesce while pending, without losing quota/completion identities.
        self.pending.append((tone, preview))
        self._next()

    def _next(self):
        if self.closed or self.controller.future is not None or not self.pending: return
        while self.pending:
            tone, preview = self.pending.popleft()
            try:
                if not preview and not enabled(SOUNDS): continue
                value = dict(tone=tone, raise_volume=enabled(RAISE_VOLUME))
            except ValueError as exc: self.feedback.emit(str(exc)); return
            self.controller.request('alert-play', value)
            return

    def _busy(self, busy):
        if not busy: self._next()

    def shutdown(self):
        self.closed = True
        self.pending.clear()
        self.controller.close()
