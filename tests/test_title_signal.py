from deck_wellness.core.snapshot import (AppRSS, MemInfo, Pressure, Snapshot,
                                         LoadAvg)
from deck_wellness.ui import title_signal


def snap(available_kb, total_kb=14_374_304, psi10=0.0, self_rss_kb=96_000):
    return Snapshot(
        ts=0.0,
        mem=MemInfo(total_kb, available_kb),
        swap_used_kb=0, swap_total_kb=7_208_724,
        pressure_memory=Pressure(psi10, psi10, psi10, 0) if psi10 is not None else None,
        pressure_io=None, pressure_cpu=None,
        load=LoadAvg(1, 1, 1, 1, 1),
        apps=(AppRSS("edge", 1_400_000, 21),),
        self_rss_kb=self_rss_kb,
    )


def test_green_when_plenty_available():
    s = title_signal.compute(snap(5_000_000))  # ~35%
    assert s.level == "green" and s.emoji == "🟢"


def test_yellow_when_available_below_20_percent():
    s = title_signal.compute(snap(2_500_000))  # ~17%
    assert s.level == "yellow" and s.emoji == "🟡"


def test_red_when_available_below_10_percent():
    s = title_signal.compute(snap(1_000_000))
    assert s.level == "red" and s.emoji == "🔴"


def test_red_when_memory_pressure_high_even_with_ram_free():
    s = title_signal.compute(snap(5_000_000, psi10=12.0))
    assert s.level == "red"


def test_yellow_when_memory_pressure_moderate():
    s = title_signal.compute(snap(5_000_000, psi10=6.0))
    assert s.level == "yellow"


def test_yellow_when_own_app_over_budget():
    s = title_signal.compute(snap(5_000_000, self_rss_kb=350_000))
    assert s.level == "yellow"


def test_unknown_when_meminfo_missing():
    s = title_signal.compute(snap(0).__class__(ts=0, mem=None, swap_used_kb=0,
        swap_total_kb=0, pressure_memory=None, pressure_io=None, pressure_cpu=None,
        load=None, apps=(), self_rss_kb=0))
    assert s.level == "unknown"


def test_text_has_brazilian_format_and_self_rss():
    s = title_signal.compute(snap(2_500_000, self_rss_kb=98_304))
    # total 14374304 kB -> 13,7 GB; avail 2500000 kB -> 2,4 GB; used -> 11,3 GB
    assert s.text.startswith("DeckWellness 🟡 ·")
    assert "11,3/13,7 GB livre 2,4" in s.text
    assert "·" in s.text
    assert "96 MB" in s.text  # 98304 kB = 96 MB
