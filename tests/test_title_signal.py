from deck_wellness.core.snapshot import (AppRSS, MemInfo, Pressure, Snapshot,
                                         LoadAvg)
from deck_wellness.ui import title_signal


def snap(available_kb, total_kb=14_374_304, psi10=0.0, self_rss_kb=96_000, tmpfs=()):
    return Snapshot(
        ts=0.0,
        mem=MemInfo(total_kb, available_kb),
        swap_used_kb=0, swap_total_kb=7_208_724,
        pressure_memory=Pressure(psi10, psi10, psi10, 0) if psi10 is not None else None,
        pressure_io=None, pressure_cpu=None,
        load=LoadAvg(1, 1, 1, 1, 1),
        apps=(AppRSS("edge", 1_400_000, 21),),
        self_rss_kb=self_rss_kb,
        tmpfs=tmpfs,
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


from deck_wellness.core.tmpfs import TmpfsVolume

GIB = 1024 ** 3


def vol(path="/tmp", total=7.24, used=0.0):
    used_bytes = int(used * GIB)
    total_bytes = int(total * GIB)
    return TmpfsVolume(path, "tmpfs", total_bytes, used_bytes, total_bytes - used_bytes)


def test_tmpfs_at_95_percent_is_red_even_with_plenty_of_ram():
    # RAM folgada (5 GB de 14 GB disponíveis): só o tmpfs pode explicar o 🔴
    s = title_signal.compute(snap(5_000_000, tmpfs=(vol(used=6.88, total=7.24),)))
    assert s.level == "red" and s.emoji == "🔴"


def test_tmpfs_at_80_percent_is_yellow():
    s = title_signal.compute(snap(5_000_000, tmpfs=(vol(used=5.8, total=7.24),)))
    assert s.level == "yellow"


def test_tmpfs_below_the_floor_does_not_touch_the_signal():
    before = title_signal.compute(snap(5_000_000))
    after = title_signal.compute(snap(5_000_000, tmpfs=(vol(used=5.0, total=7.24),)))
    assert after.level == before.level == "green"
    assert after.text == before.text


def test_the_floor_itself_is_included():
    # 6 GiB de 8 = 0,75 exato (e 0,75 é representável em binário, então este teste
    # é fronteira de verdade, não sorteio de ponto flutuante). Trocar `>=` por `>`
    # faria um volume exatamente no piso sumir do título.
    volume = TmpfsVolume("/dev/shm", "tmpfs", 8 * GIB, 6 * GIB, 2 * GIB)
    s = title_signal.compute(snap(5_000_000, tmpfs=(volume,)))
    assert s.level == "yellow" and s.text.endswith("· /dev/shm 75%")


def test_the_title_names_the_worst_watched_volume():
    # os dois passam do piso de 75%: com um só flagged, min e max dariam o mesmo
    # volume e o seletor do pior ficaria sem teste
    s = title_signal.compute(snap(5_000_000, tmpfs=(
        vol("/tmp", used=6.0, total=7.24), vol("/run/user/1000", total=1.45, used=1.40))))
    assert s.text.endswith("· /run/user/1000 97%")


def test_the_tmpfs_rule_only_escalates_never_relaxes():
    # RAM crítica continua vermelha com tmpfs tranquilo
    s = title_signal.compute(snap(1_000_000, tmpfs=(vol(used=0.5),)))
    assert s.level == "red"


def test_a_yellow_tmpfs_does_not_downgrade_a_red_machine():
    # 80% de tmpfs sozinho é amarelo; com RAM crítica o título segue vermelho,
    # só que agora dizendo as duas coisas. Afrouxar `elif level == "green"` para
    # `else` é a inversão que este teste existe para pegar.
    s = title_signal.compute(snap(1_000_000, tmpfs=(vol(used=5.8, total=7.24),)))
    assert s.level == "red" and s.emoji == "🔴"
    assert "/tmp 80%" in s.text
