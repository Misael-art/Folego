"""F3.2: métricas observadas por delta, com ausência nomeada.

CPU e I/O só existem entre duas amostras; a primeira leitura devolve None, nunca
zero. O mesmo vale para PSS (sob demanda) e inodes de um volume.
"""
from types import SimpleNamespace

import pytest

from folego.core import collector, procfs
from folego.core.tmpfs import watched_volumes


def build(fake_proc, *, pids, cpu=None):
    from fixtures_proc import build_proc, set_cpu_stat
    build_proc(fake_proc, pids=pids)
    if cpu is not None:
        set_cpu_stat(fake_proc, **cpu)
    return fake_proc


def collector_with_clocks(proc_root, sys_root, times):
    ticks = iter(times)
    return collector.MetricsCollector(
        proc_root=proc_root, sys_root=sys_root, ticks_per_sec=100,
        clock=lambda: next(ticks), wall_clock=lambda: 1_000.0)


def test_cpu_times_reads_the_aggregate_line_and_ignores_per_cpu_lines(fake_proc):
    from fixtures_proc import set_cpu_stat
    set_cpu_stat(fake_proc, user=10, nice=20, system=30, idle=40,
                 iowait=50, irq=60, softirq=70, steal=80, extra_cpus=2)

    cpu = procfs.read_cpu_times(fake_proc)

    assert (cpu.user, cpu.nice, cpu.system, cpu.idle) == (10, 20, 30, 40)
    assert (cpu.iowait, cpu.irq, cpu.softirq, cpu.steal) == (50, 60, 70, 80)
    assert cpu.total == 360 and cpu.busy == 270


def test_missing_cpu_times_is_none_not_zero(fake_proc):
    from fixtures_proc import build_proc
    build_proc(fake_proc)
    assert procfs.read_cpu_times(fake_proc) is None


def test_the_first_sample_does_not_invent_cpu_or_io(fake_proc, tmp_path):
    build(fake_proc, pids=[dict(pid=10, comm="app", utime=100, stime=50)],
          cpu=dict(user=100, idle=100))
    snap = collector_with_clocks(fake_proc, tmp_path, [100.0, 100.0]).collect()

    assert snap.cpu_busy_frac is None
    assert snap.procs[0].cpu_frac is None
    assert snap.procs[0].io_read_bps is None
    assert snap.source("cpu").usable


def test_cpu_is_a_delta_of_ticks_over_elapsed_time(fake_proc, tmp_path):
    from fixtures_proc import set_cpu_stat, set_proc_fields
    build(fake_proc, pids=[dict(pid=10, comm="app", utime=100, stime=50)],
          cpu=dict(user=100, idle=100))
    c = collector_with_clocks(fake_proc, tmp_path, [100.0, 100.0, 101.0, 101.0])
    c.collect()

    set_proc_fields(fake_proc, 10, utime=150, stime=50)
    set_cpu_stat(fake_proc, user=200, idle=200)
    snap = c.collect()

    # 50 ticks em 1 s a 100 Hz = 50% de um CPU. Global: 100 de 200 = 50%.
    assert snap.procs[0].cpu_frac == pytest.approx(50.0)
    assert snap.cpu_busy_frac == pytest.approx(0.5)


def test_a_recycled_pid_does_not_inherit_the_previous_cpu_delta(fake_proc, tmp_path):
    from fixtures_proc import set_proc_fields
    build(fake_proc, pids=[dict(pid=10, comm="app", utime=100, stime=50)])
    c = collector_with_clocks(fake_proc, tmp_path, [100.0, 100.0, 101.0, 101.0])
    c.collect()

    set_proc_fields(fake_proc, 10, utime=150, stime=50, starttime=999_999)
    snap = c.collect()

    assert snap.procs[0].starttime == 999_999
    assert snap.procs[0].cpu_frac is None


def test_process_io_is_measured_in_bytes_per_second(fake_proc, tmp_path):
    from fixtures_proc import set_proc_io
    build(fake_proc, pids=[dict(pid=10, comm="app")])
    c = collector_with_clocks(fake_proc, tmp_path, [100.0, 100.0, 101.0, 101.0])
    set_proc_io(fake_proc, 10, read_bytes=1_000, write_bytes=2_000)
    first = c.collect()

    set_proc_io(fake_proc, 10, read_bytes=1_500, write_bytes=2_600)
    second = c.collect()

    assert first.procs[0].io_read_bps is None
    assert second.procs[0].io_read_bytes == 1_500
    assert second.procs[0].io_read_bps == pytest.approx(500.0)
    assert second.procs[0].io_write_bps == pytest.approx(600.0)
    assert second.source("process_io").status == "ok"


def test_io_readable_only_for_some_processes_is_partial(fake_proc, tmp_path):
    from fixtures_proc import set_proc_io
    build(fake_proc, pids=[dict(pid=10, comm="one"), dict(pid=11, comm="two")])
    set_proc_io(fake_proc, 10)
    # pid 11 sem arquivo io: EACCES/ausência não vira zero
    snap = collector_with_clocks(fake_proc, tmp_path, [100.0, 100.0]).collect()

    assert snap.source("process_io").status == "partial"
    assert "1 de 2" in snap.source("process_io").detail


def test_process_io_absent_is_missing_not_zero(fake_proc, tmp_path):
    build(fake_proc, pids=[dict(pid=10, comm="app")])
    snap = collector_with_clocks(fake_proc, tmp_path, [100.0, 100.0]).collect()

    assert snap.source("process_io").status == "missing"
    assert snap.procs[0].io_read_bytes is None


def test_pss_is_on_demand_and_reads_smaps_rollup(fake_proc):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[dict(pid=10, comm="app")])
    (fake_proc / "10" / "smaps_rollup").write_text(
        "Rss: 2000 kB\nPss: 1234 kB\nPss_Anon: 1000 kB\n")

    assert procfs.read_pss_kb(fake_proc, 10) == 1234


def test_pss_falls_back_to_smaps_and_sums_every_mapping(fake_proc):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[dict(pid=10, comm="app")])
    (fake_proc / "10" / "smaps").write_text(
        "7f00-7f01 r-xp 00000000 00:00 0\nPss: 100 kB\n"
        "7f01-7f02 rw-p 00000000 00:00 0\nPss: 200 kB\n")

    assert procfs.read_pss_kb(fake_proc, 10) == 300


def test_pss_without_permission_is_none_not_zero(fake_proc):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[dict(pid=10, comm="app")])
    assert procfs.read_pss_kb(fake_proc, 10) is None


def test_vmrss_is_labelled_an_estimate(fake_proc):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[dict(pid=10, comm="app")])
    info = procfs.read_proc(fake_proc, 10)
    assert info.rss_is_estimate is True


def test_tmpfs_carries_bytes_and_inodes(fake_proc):
    (fake_proc / "mounts").write_text("tmpfs /tmp tmpfs rw 0 0\n")
    vfs = SimpleNamespace(f_frsize=4096, f_bsize=4096, f_blocks=100,
                          f_bfree=50, f_bavail=40,
                          f_files=1000, f_ffree=250, f_favail=200)

    volumes = watched_volumes(proc_root=str(fake_proc), statvfs_fn=lambda _p: vfs,
                              watched=("/tmp",))

    volume = volumes[0]
    assert volume.total_bytes == 409_600
    assert volume.used_bytes == 204_800
    assert volume.avail_bytes == 163_840
    assert volume.inodes_total == 1000
    assert volume.inodes_used == 750
    assert volume.inodes_avail == 200
    assert volume.inodes_frac == pytest.approx(0.75)
    assert volume.to_dict()["inodes_used"] == 750


def test_tmpfs_without_inode_numbers_does_not_divide_by_zero(fake_proc):
    (fake_proc / "mounts").write_text("tmpfs /tmp tmpfs rw 0 0\n")
    vfs = SimpleNamespace(f_frsize=4096, f_bsize=4096, f_blocks=100,
                          f_bfree=50, f_bavail=40)
    volume = watched_volumes(proc_root=str(fake_proc), statvfs_fn=lambda _p: vfs,
                             watched=("/tmp",))[0]
    assert volume.inodes_total == 0 and volume.inodes_frac == 0.0
