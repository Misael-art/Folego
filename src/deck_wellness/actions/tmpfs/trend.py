"""Regressão linear sobre a janela curta de amostras de ocupação."""
import time


def eta_hours(samples, capacity_bytes: int, *, now=None, min_samples: int = 3,
              horizon_s: float = 900.0):
    now = time.time() if now is None else now
    window = sorted(((ts, used) for ts, used in samples if now - ts <= horizon_s),
                    key=lambda s: s[0])
    if len(window) < min_samples or capacity_bytes <= 0:
        return None

    n = len(window)
    mean_x = sum(ts for ts, _ in window) / n
    mean_y = sum(used for _, used in window) / n
    denom = sum((ts - mean_x) ** 2 for ts, _ in window)
    if denom <= 0:
        return None
    slope = sum((ts - mean_x) * (used - mean_y) for ts, used in window) / denom
    if slope <= 0:
        return None

    remaining = capacity_bytes - window[-1][1]
    if remaining <= 0:
        return None
    return round(remaining / slope / 3600.0, 3)
