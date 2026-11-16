"""Shared resource policy, independent of OS collectors and desktop runtimes."""
from dataclasses import dataclass

THRESHOLDS_VERSION = 2


@dataclass(frozen=True)
class HealthThresholds:
    version: int = THRESHOLDS_VERSION
    yellow_available_frac: float = 0.20
    red_available_frac: float = 0.10
    psi_memory_yellow: float = 5.0
    psi_memory_red: float = 10.0
    psi_full_yellow: float = 5.0
    psi_full_red: float = 10.0
    self_rss_yellow_kb: int = 300_000
    tmpfs_yellow_frac: float = 0.75
    tmpfs_red_frac: float = 0.90
    stale_after_s: float = 15.0
    recovery_samples: int = 3
    thermal_margin_c: float = 5.0


def battery_band(percent: int) -> str:
    if percent <= 10:
        return 'red'
    if percent <= 25:
        return 'orange'
    if percent <= 50:
        return 'yellow'
    return 'green'
