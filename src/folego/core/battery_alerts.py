"""Battery threshold transitions, independent of Qt and audio effects."""
import time


def battery_band(percent: int) -> str:
    if percent <= 10:
        return 'red'
    if percent <= 25:
        return 'orange'
    if percent <= 50:
        return 'yellow'
    return 'green'


def remaining_text(seconds: int | None) -> str:
    if seconds is None:
        return ''
    minutes = max(1, round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h{minutes:02d}' if hours else f'{minutes} min'


class BatteryAlertTracker:
    def __init__(self):
        self.previous = None
        self.last_critical = None

    def observe(self, battery, *, now=None) -> str | None:
        """Emit one highest-priority cue on a downward crossing or each critical minute."""
        now = time.monotonic() if now is None else now
        if battery is None or battery.status != 'Discharging':
            self.previous = None
            self.last_critical = None
            return None
        current = battery.percent
        previous = self.previous
        self.previous = current
        if current <= 10:
            if self.last_critical is None or now - self.last_critical >= 60:
                self.last_critical = now
                return 'battery-10'
            return None
        self.last_critical = None
        if previous is None:
            return None  # establish a baseline on startup or after an unknown read
        for threshold in (25, 50, 75):
            if previous > threshold >= current:
                return f'battery-{threshold}'
        return None
