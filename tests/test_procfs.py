import pytest

from deck_wellness.core import procfs


@pytest.fixture
def proc(fake_proc):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[
        dict(pid=100, comm="msedge", ppid=1, rss_kb=2048),
        dict(pid=101, comm="msedge", ppid=100, rss_kb=512),
        dict(pid=200, comm="kwin_wayland", ppid=1, rss_kb=114),
    ])
    return fake_proc


def test_meminfo_reads_total_and_available(proc):
    m = procfs.read_meminfo(proc)
    assert m.mem_total_kb == 14374304
    assert m.mem_available_kb == 6242228


def test_meminfo_missing_gives_none(fake_proc):
    assert procfs.read_meminfo(fake_proc) is None


def test_pressure_parses_some_avg10(proc):
    p = procfs.read_pressure(proc, "memory")
    assert p.some_avg10 == 0.0 and p.some_total == 81109886


def test_pressure_missing_file_gives_none(proc):
    assert procfs.read_pressure(proc, "cpu") is None


def test_loadavg(proc):
    la = procfs.read_loadavg(proc)
    assert la.one == 5.04 and la.runnable == 6


def test_swaps_lists_devices(proc):
    swaps = procfs.read_swaps(proc)
    assert swaps[0].name == "/dev/zram1"
    assert swaps[0].used_kb == 3984256


def test_list_processes_returns_known_pids_with_rss(proc):
    procs = procfs.list_processes(proc)
    by_pid = {p.pid: p for p in procs}
    assert set(by_pid) >= {100, 101, 200}
    assert by_pid[100].comm == "msedge"
    assert by_pid[100].rss_kb == 2048
    assert by_pid[100].ppid == 1
    assert by_pid[100].cmdline[0] == "/usr/bin/msedge"


def test_list_processes_skips_non_numeric_and_malformed(proc):
    (proc / "self").symlink_to(proc)  # non-numeric entry
    bad = proc / "999"
    bad.mkdir()  # dir with no stat file -> skipped, not crash
    procs = procfs.list_processes(proc)
    assert all(p.pid != 999 for p in procs)
    assert len(procs) == 3


def test_pid_vanishing_mid_scan_is_ignored(fake_proc):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[dict(pid=300, comm="x")])
    (fake_proc / "300" / "stat").unlink()
    procs = procfs.list_processes(fake_proc)
    assert all(p.pid != 300 for p in procs)
