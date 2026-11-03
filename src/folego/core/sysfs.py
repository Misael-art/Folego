"""Read-only /sys parsers (zram accounting)."""
from pathlib import Path

from .. import paths
from .snapshot import ZramStat


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
