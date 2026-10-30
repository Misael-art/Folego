"""The manual central has one palette and a visible focus ring.

Contrast is measured here instead of trusted to a screenshot: all text tokens
must reach WCAG AA on every surface they can land on, and the focus colour must
stand out from the surface. There is no animation in the stylesheet, so reduced
motion has nothing to disable.
"""
import pytest

from folego.ui.theme import STYLESHEET, TOKENS

pytest.importorskip("PySide6")


def _luminance(color: str) -> float:
    raw = color.lstrip("#")
    channels = [int(raw[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [value / 12.92 if value <= 0.04045
              else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return (0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2])


def contrast(foreground: str, background: str) -> float:
    high, low = sorted((_luminance(foreground), _luminance(background)),
                       reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("surface", [TOKENS.background, TOKENS.surface,
                                     TOKENS.surface_alt])
@pytest.mark.parametrize("text", [TOKENS.text, TOKENS.muted, TOKENS.accent,
                                  TOKENS.ok, TOKENS.warning, TOKENS.danger])
def test_every_text_token_reaches_wcag_aa(text, surface):
    assert contrast(text, surface) >= 4.5


def test_the_focus_ring_is_distinct_from_every_surface():
    for surface in (TOKENS.background, TOKENS.surface, TOKENS.surface_alt):
        assert contrast(TOKENS.focus, surface) >= 3.0


def test_the_stylesheet_has_visible_focus_and_no_motion():
    lowered = STYLESHEET.lower()
    assert "qpushbutton:focus" in lowered
    assert "border: 2px solid" in lowered
    assert "animation" not in lowered
    assert "transition" not in lowered
