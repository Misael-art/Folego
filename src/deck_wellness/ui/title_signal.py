"""Pure function: Snapshot -> window-title text + colored traffic signal.

No Qt here so it is unit-testable and reusable by the tray tooltip.
"""
from dataclasses import dataclass

from ..core.snapshot import Snapshot

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


@dataclass(frozen=True)
class TitleSignal:
    level: str
    emoji: str
    text: str


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

    emoji = EMOJI[level]
    self_mb = snapshot.self_rss_kb // KB
    # values are in kB: kB->MB = /KB, kB->GB = /MB
    text = (f"DeckWellness {emoji} · {fmt1(used / MB)}/{fmt1(total / MB)} GB "
            f"livre {fmt1(avail / MB)} · app {self_mb} MB")
    return TitleSignal(level, emoji, text)


def fmt1(value_gb: float) -> str:
    return f"{value_gb:.1f}".replace(".", ",")
