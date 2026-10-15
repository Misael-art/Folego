"""The list the UI and the CLI walk: every tuning the app knows how to do.

Order is the order the user sees. A spec joins this list only when its key path
was confirmed against the installed browser, not when it looked plausible.
"""
from .model import Tuning
from .specs.background_mode import BACKGROUND_MODE
from .specs.startup_boost import STARTUP_BOOST

TUNINGS: tuple[Tuning, ...] = (BACKGROUND_MODE, STARTUP_BOOST)


def tuning_by_id(tuning_id: str) -> Tuning:
    for tuning in TUNINGS:
        if tuning.id == tuning_id:
            return tuning
    raise KeyError(f"tuning desconhecido: {tuning_id}")
