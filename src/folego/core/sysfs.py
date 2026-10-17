"""Read-only /sys parsers (zram accounting)."""
from dataclasses import dataclass
from pathlib import Path

from .. import paths


@dataclass(frozen=True)
class ZramStat:
    orig_data_kb: int
    compr_data_kb: int
    mem_used_total_kb: int


def read_zram_mm_stat(root: Path | None = None, device: str = "zram0") -> ZramStat | None:
    root = root or Path(paths.sys_root())
    try:
        raw = (root / "block" / device / "mm_stat").read_text()
    except OSError:
        return None
    parts = raw.split()
    if len(parts) < 4:
        return None
    try:
        orig, comp, _same, used = (int(parts[i]) for i in range(4))
    except ValueError:
        return None
    return ZramStat(orig // 1024, comp // 1024, used // 1024)
