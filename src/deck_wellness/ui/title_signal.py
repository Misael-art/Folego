"""Pure function: Snapshot -> window-title text + colored traffic signal.

No Qt here so it is unit-testable and reusable by the tray tooltip.
"""
from dataclasses import dataclass

from ..core.snapshot import Snapshot
from ..core.tmpfs import TmpfsVolume

EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "unknown": "⚪"}
KB = 1024
MB = 1024 * KB
GB = 1024 * MB


@dataclass(frozen=True)
class Thresholds:
    yellow_available_frac: float = 0.20
    red_available_frac: float = 0.10
    psi_memory_yellow: float = 5.0
    psi_memory_red: float = 10.0
    self_rss_yellow_kb: int = 300_000
    tmpfs_yellow_frac: float = 0.75
    tmpfs_red_frac: float = 0.90


@dataclass(frozen=True)
class TitleSignal:
    level: str
    emoji: str
    text: str


def worst_tmpfs(snapshot: Snapshot, thresholds: Thresholds) -> TmpfsVolume | None:
    """O volume em watch que merece aparecer no título, ou None enquanto todos folgam."""
    flagged = [v for v in snapshot.tmpfs if v.used_frac >= thresholds.tmpfs_yellow_frac]
    return max(flagged, key=lambda v: v.used_frac) if flagged else None


def compute(snapshot: Snapshot, thresholds: Thresholds = Thresholds()) -> TitleSignal:
    if snapshot.mem is None:
        return TitleSignal("unknown", EMOJI["unknown"], "DeckWellness ⚪ · meminfo indisponível")

    total = snapshot.mem.mem_total_kb
    avail = snapshot.mem.mem_available_kb
    used = total - avail
    frac = avail / total if total else 0.0
    psi10 = snapshot.pressure_memory.some_avg10 if snapshot.pressure_memory else 0.0

    if frac < thresholds.red_available_frac or psi10 > thresholds.psi_memory_red:
        level = "red"
    elif (frac < thresholds.yellow_available_frac
          or psi10 > thresholds.psi_memory_yellow
          or snapshot.self_rss_kb > thresholds.self_rss_yellow_kb):
        level = "yellow"
    else:
        level = "green"

    worst = worst_tmpfs(snapshot, thresholds)
    if worst is not None:
        if worst.used_frac >= thresholds.tmpfs_red_frac:
            level = "red"
        elif level == "green":
            level = "yellow"

    emoji = EMOJI[level]
    self_mb = snapshot.self_rss_kb // KB
    # values are in kB: kB->MB = /KB, kB->GB = /MB
    text = (f"DeckWellness {emoji} · {fmt1(used / MB)}/{fmt1(total / MB)} GB "
            f"livre {fmt1(avail / MB)} · app {self_mb} MB")
    if worst is not None:
        text += f" · {worst.path} {round(worst.used_frac * 100)}%"
    return TitleSignal(level, emoji, text)


def fmt1(value_gb: float) -> str:
    return f"{value_gb:.1f}".replace(".", ",")
