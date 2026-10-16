"""ETA é extrapolação, não promessa: devolve None quando não sabe.

Amostra insuficiente, tendência de queda ou volume já cheio devolvem None — nunca
0, porque 0 seria lido como "vai lotar agora", o oposto de "não tenho evidência
de crescimento".
"""
import pytest

from deck_wellness.actions.tmpfs import trend

GIB = 1024 ** 3


def test_growing_usage_extrapolates_to_the_cap():
    samples = ((0.0, 1 * GIB), (60.0, 2 * GIB), (120.0, 3 * GIB))
    got = trend.eta_hours(samples, 8 * GIB, now=120.0)
    assert got == pytest.approx(300 / 3600, abs=1e-3)      # 1 GiB/min, faltam 5 GiB


def test_declining_usage_has_no_eta():
    assert trend.eta_hours(((0.0, 5 * GIB), (60.0, 3 * GIB), (120.0, 1 * GIB)),
                           8 * GIB, now=120.0) is None


def test_flat_usage_has_no_eta():
    assert trend.eta_hours(((0.0, 2 * GIB), (60.0, 2 * GIB), (120.0, 2 * GIB)),
                           8 * GIB, now=120.0) is None


def test_two_samples_are_not_a_trend():
    assert trend.eta_hours(((0.0, 1 * GIB), (60.0, 2 * GIB)), 8 * GIB, now=60.0) is None


def test_a_full_volume_is_not_future_news():
    assert trend.eta_hours(((0.0, 7 * GIB), (60.0, 8 * GIB), (120.0, 8 * GIB)),
                           8 * GIB, now=120.0) is None


def test_samples_outside_the_window_are_ignored():
    samples = ((0.0, 0), (3000.0, 1 * GIB), (3060.0, 2 * GIB), (3120.0, 3 * GIB))
    assert trend.eta_hours(samples, 8 * GIB, now=3120.0) == pytest.approx(
        300 / 3600, abs=1e-3)


def test_no_capacity_no_answer():
    assert trend.eta_hours(((0.0, 1), (60.0, 2), (120.0, 3)), 0, now=120.0) is None
