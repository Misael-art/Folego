"""Pure function: Snapshot -> window-title text + colored traffic signal.

No Qt here so it is unit-testable and reusable by the tray tooltip. The verdict
itself lives in ``core.health``; this module only renders it and keeps the
legacy stateless entry point for callers that do not own an engine.
"""
from dataclasses import dataclass, replace

from ..core import health
from ..core.snapshot import Snapshot
from ..core.tmpfs import TmpfsVolume

EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "unknown": "⚪"}
KB = 1024
MB = 1024 * KB
GB = 1024 * MB

Thresholds = health.HealthThresholds


@dataclass(frozen=True)
class TitleSignal:
    level: str
    emoji: str
    text: str
    report: health.HealthReport | None = None


def worst_tmpfs(snapshot: Snapshot, thresholds: Thresholds) -> TmpfsVolume | None:
    """O volume em watch que merece aparecer no título, ou None enquanto todos folgam."""
    flagged = [v for v in snapshot.tmpfs if v.used_frac >= thresholds.tmpfs_yellow_frac]
    return max(flagged, key=lambda v: v.used_frac) if flagged else None


def compute(snapshot: Snapshot, thresholds: Thresholds = Thresholds(), *,
            engine: health.HealthEngine | None = None,
            now_mono: float | None = None) -> TitleSignal:
    if engine is None:
        # Chamada avulsa não tem histórico: um único juízo, sem histerese.
        engine = health.HealthEngine(
            thresholds=replace(thresholds, recovery_samples=1))
    report = engine.evaluate(snapshot, now_mono)
    level = report.level
    if level == health.UNKNOWN:
        reason = next((item for item in report.reasons
                       if item.code == "snapshot_stale"), None)
        detail = reason.message if reason is not None else "meminfo indisponível"
        return TitleSignal(level, EMOJI[level], f"Fôlego ⚪ · {detail}", report)

    total = snapshot.mem.mem_total_kb
    avail = snapshot.mem.mem_available_kb
    used = total - avail
    emoji = EMOJI[level]
    self_mb = snapshot.self_rss_kb // KB
    # values are in kB: kB->MB = /KB, kB->GB = /MB
    text = (f"Fôlego {emoji} · {fmt1(used / MB)}/{fmt1(total / MB)} GB "
            f"livre {fmt1(avail / MB)} · app {self_mb} MB")
    worst = worst_tmpfs(snapshot, thresholds)
    runtime_alert = next((r for r in report.reasons if r.code == "runtime_critical"), None)
    if runtime_alert:
        text += " · " + runtime_alert.message
    elif "tmpfs_inodes_exhausted" in report.codes():
        text += " · inodes esgotados — aplicativos podem não abrir"
    if worst is not None:
        text += f" · {worst.path} {round(worst.used_frac * 100)}%"
    return TitleSignal(level, emoji, text, report)


def fmt1(value_gb: float) -> str:
    return f"{value_gb:.1f}".replace(".", ",")
