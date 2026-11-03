"""F3.1: relógio monotônico, timestamp humano, idade e qualidade por fonte.

A regra central: ausente/ilegível/antigo não pode virar "vazio/seguro". Estes
testes exercitam a coleta real sobre um /proc falso e o gate que a UI/CLI pode
consultar antes de agir.
"""
from datetime import datetime

import pytest

from folego.core import collector, procfs
from folego.core.snapshot import (ERROR, MISSING, OK, PARTIAL, MemInfo,
                                  Pressure, Snapshot, SourceQuality)


def env(fake_proc, *, pids=(), **kwargs):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=list(pids), **kwargs)
    return fake_proc


def test_collector_stamps_monotonic_wall_duration_and_human_time(fake_proc, tmp_path):
    env(fake_proc, pids=[dict(pid=10, comm="app")])
    ticks = iter([100.0, 100.25])
    snap = collector.MetricsCollector(
        proc_root=fake_proc, sys_root=tmp_path,
        clock=lambda: next(ticks),
        wall_clock=lambda: 1_700_000_000.0,
    ).collect()

    assert snap.mono == 100.25
    assert snap.duration_s == pytest.approx(0.25)
    assert snap.ts == 1_700_000_000.0
    parsed = datetime.fromisoformat(snap.ts_iso)
    assert parsed.tzinfo is not None and parsed.timestamp() == snap.ts
    assert snap.sources and all(q.mono == snap.mono for q in snap.sources)


def test_an_empty_wall_clock_has_no_invented_human_timestamp():
    snap = Snapshot(ts=0.0, mem=None, swap_used_kb=0, swap_total_kb=0,
                    pressure_memory=None, pressure_io=None, pressure_cpu=None,
                    load=None, apps=(), self_rss_kb=0)
    assert snap.ts_iso == ""


def test_age_and_staleness_use_the_monotonic_clock():
    snap = Snapshot(
        ts=10.0, mem=MemInfo(100, 50), swap_used_kb=0, swap_total_kb=0,
        pressure_memory=None, pressure_io=None, pressure_cpu=None,
        load=None, apps=(), self_rss_kb=0, mono=100.0,
        sources=(SourceQuality("meminfo", OK, mono=100.0),))

    assert snap.age_s(now_mono=112.5) == 12.5
    assert not snap.is_stale(15.0, now_mono=112.5)
    assert snap.is_stale(15.0, now_mono=116.0)
    assert snap.action_blockers(required=("meminfo",), max_age_s=15.0,
                                now_mono=116.0)


def test_a_snapshot_without_a_monotonic_clock_can_never_authorize_an_action():
    snap = Snapshot(ts=1.0, mem=MemInfo(100, 50), swap_used_kb=0,
                    swap_total_kb=0, pressure_memory=None, pressure_io=None,
                    pressure_cpu=None, load=None, apps=(), self_rss_kb=0,
                    sources=(SourceQuality("meminfo", OK),))

    assert snap.is_stale(3600.0, now_mono=2.0)
    blockers = snap.action_blockers(required=("meminfo",), now_mono=2.0)
    assert any("sem relógio monotônico" in reason for reason in blockers)


def test_missing_meminfo_is_named_and_blocks_the_action(fake_proc, tmp_path):
    env(fake_proc, meminfo=None)
    snap = collector.MetricsCollector(proc_root=fake_proc,
                                      sys_root=tmp_path).collect()

    quality = snap.source("meminfo")
    assert quality.status == MISSING
    assert not quality.usable
    assert any("meminfo missing" in reason
               for reason in snap.action_blockers(now_mono=snap.mono))


def test_a_present_but_malformed_file_is_error_not_missing(fake_proc, tmp_path):
    env(fake_proc, meminfo="MemTotal: 100 kB\n")  # sem MemAvailable
    snap = collector.MetricsCollector(proc_root=fake_proc,
                                      sys_root=tmp_path).collect()

    quality = snap.source("meminfo")
    assert quality.status == ERROR
    assert "malformado" in quality.detail
    assert snap.source("meminfo").status != MISSING


def test_partial_process_scan_is_usable_and_names_the_bad_entries(fake_proc, tmp_path):
    env(fake_proc, pids=[dict(pid=10, comm="app")])
    bad = fake_proc / "999"
    bad.mkdir()
    (bad / "stat").write_text("not a valid stat line\n")

    snap = collector.MetricsCollector(proc_root=fake_proc,
                                      sys_root=tmp_path).collect()

    quality = snap.source("processes")
    assert quality.status == PARTIAL and quality.usable
    assert "999" in quality.detail
    assert snap.action_blockers(required=("processes",),
                                now_mono=snap.mono) == ()


def test_scan_processes_distinguishes_vanish_from_unreadable(fake_proc):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[dict(pid=10, comm="app")])
    unreadable = fake_proc / "11"
    unreadable.mkdir()
    (unreadable / "stat").write_text("broken\n")

    scan = procfs.scan_processes(fake_proc)

    assert [p.pid for p in scan.procs] == [10]
    assert scan.entries == 2
    assert scan.unreadable == (11,)
    assert scan.error is None


def test_unreadable_proc_root_is_an_error_not_an_empty_process_list(tmp_path):
    scan = procfs.scan_processes(tmp_path / "does-not-exist")
    assert scan.error is not None
    assert scan.procs == ()


def test_pressure_full_is_parsed_and_absence_is_none_not_zero(fake_proc):
    from fixtures_proc import build_proc
    build_proc(fake_proc)

    pressure = procfs.read_pressure(fake_proc, "memory")
    assert pressure.some_total == 81109886
    assert pressure.full_avg10 == 0.0
    assert pressure.full_total == 77447214

    (fake_proc / "pressure" / "memory").write_text(
        "some avg10=1.00 avg60=2.00 avg300=3.00 total=4\n")
    only_some = procfs.read_pressure(fake_proc, "memory")
    assert only_some.some_avg10 == 1.0
    assert only_some.full_avg10 is None
    assert only_some.full_total is None


def test_zram_is_carried_with_quality(fake_proc, tmp_path):
    env(fake_proc)
    z = tmp_path / "block" / "zram0"
    z.mkdir(parents=True)
    (z / "mm_stat").write_text("4081590272 811380737 104857600 893075456 0 0 0 0 0 0\n")

    snap = collector.MetricsCollector(proc_root=fake_proc,
                                      sys_root=tmp_path).collect()

    assert snap.zram.mem_used_total_kb == 102400
    assert snap.source("zram").status == OK


def test_missing_zram_is_named_but_does_not_void_the_snapshot(fake_proc, tmp_path):
    env(fake_proc)
    snap = collector.MetricsCollector(proc_root=fake_proc,
                                      sys_root=tmp_path).collect()

    assert snap.zram is None
    assert snap.source("zram").status == MISSING
    assert snap.source("meminfo").usable


def test_a_truncated_process_scan_is_partial_and_names_the_limit(fake_proc, tmp_path):
    env(fake_proc, pids=[dict(pid=10, comm="a"), dict(pid=11, comm="b"),
                         dict(pid=12, comm="c")])
    snap = collector.MetricsCollector(
        proc_root=fake_proc, sys_root=tmp_path, max_processes=1).collect()

    quality = snap.source("processes")
    assert quality.status == PARTIAL
    assert "limitada a 1 de 3" in quality.detail
    assert len(snap.procs) == 1


def test_scan_processes_limit_is_explicit_and_deterministic(fake_proc):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[dict(pid=10, comm="a"), dict(pid=11, comm="b"),
                                dict(pid=12, comm="c")])

    scan = procfs.scan_processes(fake_proc, limit=2)

    assert [p.pid for p in scan.procs] == [10, 11]
    assert scan.entries == 3 and scan.truncated is True
    assert scan.unreadable == ()


def test_a_failing_tmpfs_seam_is_named_and_keeps_the_rest(fake_proc, tmp_path):
    env(fake_proc)

    def broken(_root):
        raise RuntimeError("seam quebrada")

    snap = collector.MetricsCollector(proc_root=fake_proc, sys_root=tmp_path,
                                      tmpfs_fn=broken).collect()

    quality = snap.source("tmpfs")
    assert quality.status == ERROR
    assert "seam quebrada" in quality.detail
    assert snap.tmpfs == ()
    assert snap.mem is not None


def test_missing_mounts_is_missing_not_a_tmpfs_error(fake_proc, tmp_path):
    env(fake_proc)
    snap = collector.MetricsCollector(proc_root=fake_proc,
                                      sys_root=tmp_path).collect()

    assert snap.source("tmpfs").status == MISSING
    assert snap.errors == (), "a ausência de /proc/mounts não é falha da amostra"
