"""Desktop capability matrix without pretending to know more than the session.

Wayland deliberately gives no portable way to place a window at absolute
coordinates or to prove that ``keep above`` was honoured. The compact control
therefore treats those capabilities as *unproven* on Wayland and falls back to
the tray + a normal compact window instead of stealing focus or fighting the
compositor. X11 exposes both, so the same code may request them there.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class DesktopCapabilities:
    session_type: str
    platform: str
    tray: bool
    absolute_position: bool
    keep_above: bool
    autostart_hint: bool
    note: str = ""

    @property
    def compact_fallback(self) -> bool:
        return not (self.absolute_position and self.keep_above)


def detect(*, session_type: str | None = None, platform: str | None = None,
           tray: bool = False) -> DesktopCapabilities:
    """Classify the session; unknown is a first-class answer, not X11."""
    session = (session_type or "unknown").lower()
    platform = (platform or "unknown").lower()
    wayland = session == "wayland" or "wayland" in platform
    x11 = session == "x11" or "x11" in platform
    if wayland:
        return DesktopCapabilities(
            session, platform, tray, absolute_position=False, keep_above=False,
            autostart_hint=True,
            note=("Wayland: posição absoluta e keep-above não são comprováveis; "
                  "usando janela compacta comum e bandeja quando disponível"))
    if x11:
        return DesktopCapabilities(
            session, platform, tray, absolute_position=True, keep_above=True,
            autostart_hint=True,
            note="X11: posição e keep-above disponíveis")
    return DesktopCapabilities(
        session, platform, tray, absolute_position=False, keep_above=False,
        autostart_hint=False,
        note="sessão desconhecida: nenhuma capacidade de janela é presumida")
