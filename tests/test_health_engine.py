"""F3.3: HealthEngine puro — histerese, motivos estruturados e versão.

A regra de segurança: ausência/idade não viram verde nem zero. A regra de
estabilidade: piorar é imediato; melhorar exige amostras consecutivas.
"""
import pytest

from folego.core.health import (GREEN, RED, THRESHOLDS_VERSION, UNKNOWN, YELLOW,
                                HealthEngine, HealthThresholds)
from folego.core.snapshot import (AppRSS, MemInfo, OK, Pressure, Snapshot,
                                  SourceQuality, TmpfsVolume)
from folego.ui import title_signal

GIB = 1024 ** 3


@pytest.mark.parametrize("volume,code", [
    (TmpfsVolume("/runtime", "tmpfs", 1000, 100, 900, 100, 100, 0,
                 is_runtime=True), "tmpfs_inodes_exhausted"),
    (TmpfsVolume("/runtime", "tmpfs", 1000, 1000, 0,
                 is_runtime=True), "tmpfs_bytes_exhausted"),
])
def test_exhausted_runtime_is_critical_even_when_ram_is_healthy(volume, code):
    report = judge(snap(tmpfs=(volume,)))
    assert report.level == RED and code in report.codes()
    assert any("aplicativos podem não abrir" in r.message for r in report.reasons)


def test_unknown_volume_capacity_never_looks_healthy():
    volume = TmpfsVolume("/runtime", "tmpfs", 0, 0, 0,
                         quality="error", error="denied", is_runtime=True)
    report = judge(snap(tmpfs=(volume,)))
    assert report.level != GREEN and "tmpfs_unknown" in report.codes()


def test_unsupported_inode_counts_are_not_exhaustion():
    volume = TmpfsVolume("/runtime", "tmpfs", 1000, 100, 900,
                         is_runtime=True)
    report = judge(snap(tmpfs=(volume,)))
    assert "tmpfs_inodes_exhausted" not in report.codes()


def snap(*, available_kb=5_000_000, total_kb=14_374_304, psi10=0.0,
         full10=None, self_rss_kb=96_000, tmpfs=(), mono=100.0, mem=True,
         pressure=True, sources=()):
    return Snapshot(
        ts=1_000.0, mem=MemInfo(total_kb, available_kb) if mem else None,
        swap_used_kb=0, swap_total_kb=7_208_724,
        pressure_memory=Pressure(psi10, psi10, psi10, 0, full_avg10=full10)
        if pressure else None,
        pressure_io=None, pressure_cpu=None, load=None,
        apps=(AppRSS("edge", 400_000, 12),), self_rss_kb=self_rss_kb,
        tmpfs=tmpfs, mono=mono, sources=sources)


def judge(snapshot, now=None, **thresholds):
    engine = HealthEngine(thresholds=HealthThresholds(**thresholds))
    return engine.evaluate(snapshot, snapshot.mono if now is None else now)


def test_every_report_carries_the_thresholds_version():
    report = judge(snap())
    assert report.thresholds_version == THRESHOLDS_VERSION == 1
    custom = judge(snap(), version=7)
    assert custom.thresholds_version == 7


def test_missing_meminfo_is_unknown_and_has_a_structured_reason():
    report = judge(snap(mem=False))
    assert report.level == UNKNOWN
    assert "meminfo_missing" in report.codes()
    reason = next(r for r in report.reasons if r.code == "meminfo_missing")
    assert reason.source == "meminfo" and reason.severity == "critico"


def test_a_stale_sample_is_unknown_even_if_its_numbers_look_green():
    report = judge(snap(), now=116.0)  # 16 s desde a coleta, limite 15
    assert report.level == UNKNOWN and report.stale
    assert report.age_s == pytest.approx(16.0)
    assert "snapshot_stale" in report.codes()


def test_a_real_sample_without_a_monotonic_clock_is_unknown():
    sources = (SourceQuality("meminfo", OK, mono=0.0),)
    report = judge(snap(mono=0.0, sources=sources))
    assert report.level == UNKNOWN
    assert "snapshot_stale" in report.codes()


def test_a_legacy_synthetic_snapshot_without_sources_is_still_judged():
    """Testes puros e chamadas antigas não declaram fontes: não há como provar
    idade, mas também não há uma coleta real para invalidar."""
    assert judge(snap(mono=0.0)).level == GREEN


def test_absent_pressure_is_named_and_is_not_treated_as_zero():
    report = judge(snap(pressure=False))
    assert report.level == GREEN
    assert "pressure_missing" in report.codes()
    assert "psi_some_red" not in report.codes()


def test_psi_some_and_full_are_independent_rules():
    assert judge(snap(psi10=12.0)).level == RED
    assert judge(snap(psi10=0.0, full10=12.0)).level == RED
    assert "psi_full_red" in judge(snap(full10=12.0)).codes()


def test_full_psi_absent_does_not_fire_a_rule():
    report = judge(snap(psi10=0.0, full10=None))
    assert report.level == GREEN
    assert "psi_full_red" not in report.codes()


def test_tmpfs_reason_names_the_path_value_and_threshold():
    volume = TmpfsVolume("/tmp", "tmpfs", 8 * GIB, int(7.5 * GIB), int(0.5 * GIB))
    report = judge(snap(tmpfs=(volume,)))
    assert report.level == RED
    reason = next(r for r in report.reasons if r.code == "tmpfs_red")
    assert reason.value == pytest.approx(7.5 / 8)
    assert reason.threshold == 0.90
    assert "/tmp" in reason.message


def test_self_rss_over_budget_is_yellow():
    assert judge(snap(self_rss_kb=350_000)).level == YELLOW


def test_the_app_itself_under_budget_does_not_raise_the_signal():
    assert judge(snap(self_rss_kb=96_000)).level == GREEN


def test_escalation_is_immediate_but_recovery_needs_consecutive_samples():
    engine = HealthEngine(thresholds=HealthThresholds(recovery_samples=2))
    red = snap(available_kb=1_000_000)
    green = snap()

    assert engine.evaluate(green, 100.0).level == GREEN
    assert engine.evaluate(red, 100.0).level == RED, "piorar não espera"
    assert engine.evaluate(green, 100.0).level == RED, "um alívio não apaga"
    assert engine.evaluate(green, 100.0).level == YELLOW, "desce um degrau"
    assert engine.evaluate(green, 100.0).level == YELLOW
    assert engine.evaluate(green, 100.0).level == GREEN


def test_a_held_signal_records_why_it_did_not_follow_the_raw_level():
    engine = HealthEngine(thresholds=HealthThresholds(recovery_samples=3))
    engine.evaluate(snap(available_kb=1_000_000), 100.0)
    report = engine.evaluate(snap(), 100.0)

    assert report.raw_level == GREEN and report.level == RED
    assert "hysteresis" in report.codes()


def test_the_title_renders_the_stable_level_and_exposes_the_report():
    engine = HealthEngine(thresholds=HealthThresholds(recovery_samples=3))
    red = title_signal.compute(snap(available_kb=1_000_000), engine=engine,
                               now_mono=100.0)
    held = title_signal.compute(snap(), engine=engine, now_mono=100.0)

    assert red.level == RED and red.emoji == "🔴"
    assert held.level == RED and held.report.raw_level == GREEN
    assert "🔴" in held.text


def test_the_title_says_unknown_for_a_stale_sample():
    engine = HealthEngine()
    signal = title_signal.compute(snap(), engine=engine, now_mono=200.0)
    assert signal.level == UNKNOWN and "amostra antiga" in signal.text


def test_quality_problems_are_reasons_but_only_red_escalates():
    sources = (
        SourceQuality("meminfo", OK, mono=100.0),
        SourceQuality("processes", "partial", "1 entrada ilegível", mono=100.0),
    )
    report = judge(snap(sources=sources))
    assert report.level == GREEN
    assert "source_partial" in report.codes()
    assert report.degraded


def test_custom_thresholds_change_the_verdict_without_renaming_the_rules():
    strict = judge(snap(available_kb=2_500_000), yellow_available_frac=0.50)
    assert strict.level == YELLOW
    assert strict.codes().count("memoria_yellow") == 1
