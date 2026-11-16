"""One AI observation owner, independent of floating-widget visibility."""
from collections import deque
import time
from PySide6.QtCore import QObject, Signal

from ..core import ai_sessions
from ..core.agent_deliveries import DeliveryMonitor
from .alert_sounds import AlertSounds
from .workers import Poller


class AIMonitor(QObject):
    quotas_ready = Signal(object)
    deliveries_ready = Signal(object)
    web_mcp_reported = Signal(object)
    web_capacity_reported = Signal(object)

    def __init__(self, parent=None, *, collect_fn=None, deliveries=None, alerts=None):
        super().__init__(parent)
        self.items = [ai_sessions.unknown(p) for p in ai_sessions.NAMES]
        self.delivery_items = []
        self._started_at = time.time()
        self._reported_web_mcp_ids = set()
        self._reported_web_mcp_order = deque()
        self.deliveries = deliveries or DeliveryMonitor()
        from ..actions.web_recovery import WebRecovery
        self.web_recovery = WebRecovery(self.deliveries) if deliveries is None else None
        self.alerts = alerts or AlertSounds(self)
        self.poller = Poller(collect_fn or ai_sessions.collect, interval_s=60, parent=self, offload=True)
        self.delivery_poller = Poller(self._collect_deliveries, interval_s=5, parent=self, offload=True)
        self.poller.snapshot_ready.connect(self.set_items)
        self.delivery_poller.snapshot_ready.connect(self.set_deliveries)
        self.poller.error.connect(lambda _: self.set_items([ai_sessions.unknown(p, 'Consulta falhou') for p in ai_sessions.NAMES]))
        self.delivery_poller.error.connect(lambda _: self.set_deliveries([dict(provider=p, count=None, pending=[]) for p in ai_sessions.NAMES]))
        self.destroyed.connect(self.poller._stop.set)
        self.destroyed.connect(self.delivery_poller._stop.set)

    def _collect_deliveries(self):
        rows = self.deliveries.collect()
        if self.web_recovery is not None:
            self.web_recovery.handle(rows, since=self._started_at)
        return rows

    def set_items(self, items):
        self.items = items
        self.alerts.observe('quotas', items)
        self.quotas_ready.emit(items)

    def set_deliveries(self, rows):
        self.delivery_items = rows
        for row in rows:
            if row.get('provider') != 'web': continue
            for receipt in row.get('pending', ()):
                if not (receipt.get('reported_web_mcp_error') or receipt.get('web_capacity_error')): continue
                key = (receipt.get('session'), receipt.get('event'))
                if None in key or key in self._reported_web_mcp_ids: continue
                if len(self._reported_web_mcp_order) == 2048:
                    self._reported_web_mcp_ids.remove(self._reported_web_mcp_order.popleft())
                self._reported_web_mcp_order.append(key)
                self._reported_web_mcp_ids.add(key)
                if receipt.get('at', 0) >= self._started_at:
                    if receipt.get('web_capacity_error'):
                        self.web_capacity_reported.emit(receipt)
                    else:
                        self.web_mcp_reported.emit(receipt)
        self.alerts.observe('deliveries', rows)
        self.deliveries_ready.emit(rows)

    def start(self):
        self.alerts.start()
        for poller in (self.poller, self.delivery_poller):
            poller.start(); poller.request()

    def pause(self):
        self.poller.pause(); self.delivery_poller.pause()

    def shutdown(self):
        self.poller.stop(); self.delivery_poller.stop(); self.alerts.shutdown()
