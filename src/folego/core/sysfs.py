"""Read-only /sys parsers (zram accounting)."""
from pathlib import Path

from .. import paths
from .snapshot import ZramStat


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
