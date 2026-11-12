"""Battery threshold transitions, independent of Qt and audio effects."""
import time

from .snapshot import OK, Snapshot
from .policy import battery_band


def remaining_text(seconds: int | None) -> str:
    if seconds is None:
        return ''
    minutes = max(1, round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h{minutes:02d}' if hours else f'{minutes} min'


# A worn pack or miscalibrated gauge can report 50-70% while the cells sag
# below the cutoff under load and the host loses power without a log. Only a
# kernel-reported design minimum defines the reference; no cell-count guess.
# Levels are fractions of that reference, lowest bound first.
VOLTAGE_LEVELS = (('stable', 0.96), ('acceptable', 0.93), ('attention', 0.90))
VOLTAGE_BANDS = {'stable': 'green', 'acceptable': 'yellow', 'attention': 'orange',
                 'critical': 'red'}
VOLTAGE_NAMES = {'stable': 'estável', 'acceptable': 'aceitável', 'attention': 'atenção',
                 'critical': 'crítica'}


def voltage_level(battery) -> str | None:
    """Classify a discharging pack against its design minimum; unknown stays None.

    Charger voltage masks the cells, so only discharge readings are classified.
    """
    if battery is None or battery.status != 'Discharging':
        return None
    voltage, minimum = battery.voltage_uv, getattr(battery, 'voltage_min_design_uv', None)
    if voltage is None or minimum is None:
        return None
    for name, fraction in VOLTAGE_LEVELS:
        if voltage >= minimum * fraction:
            return name
    return 'critical'


def voltage_sag(battery) -> bool:
    """True when a discharging pack is below 90% of its design minimum voltage."""
    return voltage_level(battery) == 'critical'


def voltage_text(battery) -> str:
    return f'{battery.voltage_uv / 1_000_000:.2f} V'.replace('.', ',')


def power_supply_status(snapshot: Snapshot, *, now_mono=None) -> dict:
    """Describe observed power without inferring charger health or reset cause."""
    if snapshot.is_stale(15, now_mono):
        return {'state': 'unknown', 'message': 'Alimentação desconhecida · amostra antiga.'}
    battery = snapshot.battery if snapshot.source('battery').status == OK else None
    online = (snapshot.external_power_online
              if snapshot.source('external_power').status == OK else None)
    parts = ['Energia externa ' + {True: 'conectada', False: 'desconectada',
                                  None: 'desconhecida'}[online]]
    level = voltage_level(battery)
    if battery:
        parts.append(f'bateria {battery.percent}%')
        if battery.voltage_uv is not None:
            parts.append(voltage_text(battery))
        if battery.current_ua is not None:
            parts.append(f'{battery.current_ua / 1_000_000:.2f} A'.replace('.', ','))
        if level in ('attention', 'critical'):
            parts.append(f'tensão em {VOLTAGE_NAMES[level]}')
        elif battery.status == 'Discharging':
            parts.append('descarregando')
        elif battery.status == 'Charging':
            parts.append('carregando')
    else:
        parts.append('bateria desconhecida')
    if online is True and battery and battery.status == 'Discharging':
        parts.append('bateria em descarga com energia externa presente')
    state = (level if level in ('attention', 'critical') else
             'unknown' if online is None or battery is None else 'observed')
    return {'state': state, 'message': ' · '.join(parts)}


class ExternalPowerTracker:
    """Notify on observed disconnection or sustained discharge on external power."""

    def __init__(self):
        self.boot_id = ''
        self.previous_mono = None
        self.online = None
        self.discharge_streak = 0
        self.last_notice = {}

    def observe(self, snapshot: Snapshot, *, now_mono=None) -> dict | None:
        now = time.monotonic() if now_mono is None else now_mono
        if snapshot.boot_id != self.boot_id:
            self.boot_id = snapshot.boot_id
            self.previous_mono = self.online = None
            self.discharge_streak = 0
            self.last_notice.clear()
        if snapshot.is_stale(15, now) or snapshot.source('external_power').status != OK:
            self.online = None
            self.discharge_streak = 0
            return None
        if self.previous_mono is not None:
            if snapshot.mono <= self.previous_mono:
                return None
            if snapshot.mono - self.previous_mono > 20:
                self.online = None
                self.discharge_streak = 0
        self.previous_mono = snapshot.mono
        online, previous = snapshot.external_power_online, self.online
        self.online = online
        battery = snapshot.battery if snapshot.source('battery').status == OK else None
        discharging = online is True and battery and battery.status == 'Discharging'
        self.discharge_streak = self.discharge_streak + 1 if discharging else 0
        kind = None
        if previous is True and online is False:
            kind = 'disconnected'
            title = 'Alimentação · carregador desconectado'
            detail = ('A alimentação externa deixou de ser detectada. Confira o cabo e '
                      'o carregador e salve o trabalho se a tensão cair.')
        elif self.discharge_streak >= 2:
            kind = 'discharging-on-external'
            title = 'Alimentação · bateria descarregando na tomada'
            detail = ('A energia externa está presente, mas a bateria continua descarregando '
                      'em leituras consecutivas. Confira o carregador, cabo e dock.')
        if kind is None:
            return None
        last = self.last_notice.get(kind)
        if last is not None and now - last < 300:
            return None
        self.last_notice[kind] = now
        return {'title': title, 'message': detail}


class VoltageSagNotice:
    """One notice per sustained critical sag; a single load spike is not enough."""

    def __init__(self, *, repeat_s=300):
        self.repeat_s = repeat_s
        self.streak = 0
        self.last = None

    def observe(self, battery, *, now=None) -> bool:
        now = time.monotonic() if now is None else now
        if not voltage_sag(battery):
            self.streak = 0
            if voltage_level(battery) != 'attention':
                self.last = None  # recovered or unknown: the next sag is a new event
            return False
        self.streak += 1
        if self.streak < 2 or (self.last is not None and now - self.last < self.repeat_s):
            return False
        self.last = now
        return True


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
        if current <= 10 or voltage_sag(battery):
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
