"""Read-only /sys parsers (zram accounting)."""
from pathlib import Path

from .. import paths
from .snapshot import BatteryInfo, SourceQuality, ZramStat, ERROR, MISSING, OK


def _battery_int(path: Path, *, minimum=0, maximum=10**12) -> int | None:
    try:
        value = int(path.read_text().strip())
    except (OSError, ValueError):
        return None
    return value if minimum <= value <= maximum else None


def read_battery(root: Path) -> tuple[BatteryInfo | None, SourceQuality]:
    """Read the kernel power-supply ABI; never infer a healthy battery from gaps."""
    supply = root / 'class/power_supply'
    try:
        entries = list(supply.iterdir())
    except FileNotFoundError:
        return None, SourceQuality('battery', MISSING, 'sem fonte de bateria')
    except OSError:
        return None, SourceQuality('battery', ERROR, 'inventário de energia ilegível')
    if len(entries) > 64:
        return None, SourceQuality('battery', ERROR, 'inventário de energia excede o limite')
    batteries = []
    for entry in entries:
        try:
            kind = (entry / 'type').read_text().strip()
        except OSError:
            return None, SourceQuality('battery', ERROR, 'tipo da fonte ilegível')
        if kind == 'Battery':
            batteries.append(entry)
    if not batteries:
        return None, SourceQuality('battery', MISSING, 'equipamento sem bateria observada')
    if len(batteries) != 1:
        return None, SourceQuality('battery', ERROR, 'múltiplas baterias sem agregação confiável')
    path = batteries[0]
    percent = _battery_int(path / 'capacity', maximum=100)
    try:
        status = (path / 'status').read_text().strip()
    except OSError:
        status = ''
    if percent is None or status not in ('Charging', 'Discharging', 'Full', 'Not charging'):
        return None, SourceQuality('battery', ERROR, 'percentual ou estado da bateria inválido')
    remaining = None
    if status == 'Discharging':
        for name in ('time_to_empty_avg', 'time_to_empty_now'):
            remaining = _battery_int(path / name, minimum=1, maximum=7 * 86400)
            if remaining is not None:
                break
        if remaining is None:
            for available, rate in (('energy_now', 'power_now'), ('charge_now', 'current_now')):
                amount = _battery_int(path / available)
                draw = _battery_int(path / rate, minimum=1)
                if amount is not None and draw is not None:
                    estimate = round(amount * 3600 / draw)
                    if 0 < estimate <= 7 * 86400:
                        remaining = estimate
                        break
    return BatteryInfo(percent, status, remaining), SourceQuality('battery', OK)


def read_temperature(root: Path) -> tuple[float | None, str]:
    """CPU/SoC preferred; ACPI system fallback, never a disk/GPU temperature."""
    import itertools
    values = []
    acpi = []
    try:
        boards = list(itertools.islice((root / 'class/hwmon').glob('hwmon*'), 65))
        if len(boards) > 64: return None, ''
        for board in boards:
            try:
                name = (board / 'name').read_text().strip()
                if name not in ('coretemp', 'k10temp', 'zenpower', 'cpu_thermal', 'soc_thermal', 'acpitz'): continue
                inputs = list(itertools.islice(board.glob('temp*_input'), 33))
                if len(inputs) > 32: continue
                for item in inputs:
                    try:
                        value = int(item.read_text().strip()) / 1000
                        if -20 <= value <= 150:
                            (acpi if name == 'acpitz' else values).append((value, name))
                    except (OSError, ValueError): pass
            except OSError: continue
        if values: return max(values)
        zones = list(itertools.islice((root / 'class/thermal').glob('thermal_zone*'), 65))
        if len(zones) > 64: return None, ''
        for zone in zones:
            try:
                name = (zone / 'type').read_text().strip()
                if name.casefold() not in ('x86_pkg_temp', 'cpu-thermal', 'cpu_thermal', 'soc_thermal'): continue
                value = int((zone / 'temp').read_text().strip()) / 1000
                if -20 <= value <= 150: values.append((value, name))
            except (OSError, ValueError): continue
    except OSError: pass
    return max(values) if values else max(acpi) if acpi else (None, '')


def read_fan_speed(root: Path) -> tuple[int | None, str]:
    """Read a CPU-labelled or first host fan tachometer; never use a GPU fan."""
    import itertools

    fans: list[tuple[bool, str, int]] = []
    try:
        boards = list(itertools.islice((root / 'class/hwmon').glob('hwmon*'), 65))
        if len(boards) > 64:
            return None, ''
        for board in boards:
            try:
                name = (board / 'name').read_text().strip()
                if name in ('amdgpu', 'nouveau', 'nvme'):
                    continue
                inputs = list(itertools.islice(board.glob('fan*_input'), 33))
                if len(inputs) > 32:
                    continue
                for item in inputs:
                    try:
                        speed = int(item.read_text().strip())
                        if not 0 <= speed <= 100_000:
                            continue
                        label_path = item.with_name(item.name.replace('_input', '_label'))
                        try:
                            label = label_path.read_text().strip()[:80]
                        except OSError:
                            label = ''
                        source = f'{name} · {label or item.name.removesuffix("_input")}'
                        cpu_fan = 'cpu' in label.casefold() or 'processor' in label.casefold()
                        fans.append((cpu_fan, source, speed))
                    except (OSError, ValueError):
                        continue
            except OSError:
                continue
    except OSError:
        return None, ''
    if not fans:
        return None, ''
    _, source, speed = min(fans, key=lambda fan: (not fan[0], fan[1]))
    return speed, source


def read_thermal_trips(root: Path, sensor: str) -> tuple[float | None, float | None]:
    """ACPI limits for the ACPI reading only; unrelated zones prove nothing."""
    if sensor != 'acpitz':
        return None, None
    import itertools
    passive = critical = None
    matches = 0
    try:
        zones = list(itertools.islice((root / 'class/thermal').glob('thermal_zone*'), 33))
        if len(zones) > 32:
            return None, None
        for zone in zones:
            try:
                if (zone / 'type').read_text().strip() != sensor:
                    continue
                matches += 1
                trips = list(itertools.islice(zone.glob('trip_point_*_type'), 33))
                if len(trips) > 32:
                    return None, None
                for item in trips:
                    kind = item.read_text().strip()
                    if kind not in ('passive', 'critical'):
                        continue
                    value = int(item.with_name(item.name.replace('_type', '_temp')).read_text().strip()) / 1000
                    if not 20 <= value <= 150:
                        continue
                    if kind == 'passive':
                        passive = value if passive is None else min(passive, value)
                    else:
                        critical = value if critical is None else min(critical, value)
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    if matches != 1:
        return None, None
    return passive, critical


def read_zram_mm_stat(root: Path | None = None, device: str = "zram0") -> ZramStat | None:
    root = root or Path(paths.sys_root())
    try:
        raw = (root / "block" / device / "mm_stat").read_text()
    except OSError:
        return None
    parts = raw.split()
    # ABI do kernel (admin-guide/blockdev/zram): orig comp mem_used_total mem_limit
    # mem_used_max same_pages pages_compacted ... — o usado é o TERCEIRO campo; o
    # quarto é o limite configurado.
    if len(parts) < 3:
        return None
    try:
        orig, comp, used = (int(parts[i]) for i in range(3))
    except ValueError:
        return None
    return ZramStat(orig // 1024, comp // 1024, used // 1024)
