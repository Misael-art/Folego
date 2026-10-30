import pytest

from folego.core import procfs


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


def test_stat_uses_the_real_proc_field_layout():
    """Regressão: utime/stime/starttime são 11/12/19 depois do comm.

    O layout abreviado do fixture antigo escondia o deslocamento; num /proc real
    isso lia cmajflt como utime e nice como starttime — justamente a identidade
    que o reaper usa para não matar um PID reciclado.
    """
    raw = ("4242 (worker with spaces) R 1 4242 4242 0 -1 4194304 2152 0 0 0 "
           "7 2 0 0 20 0 1 0 3032351 22642688 3595 0\n")
    parsed = procfs._parse_stat(raw)
    assert parsed == (4242, "R", 1, 4242, 4242, 7, 2, 3032351)


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


def test_a_comm_vanishing_between_exists_and_read_does_not_abort(fake_proc):
    """F1.8/R16: o `comm.exists()` seguido de `read_text()` fica fora do bloco.

    Aqui a corrida é simulada com um diretório no lugar do arquivo: `exists()`
    devolve True e `read_text()` levanta OSError. O processo não pode derrubar a
    coleta inteira.
    """
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[dict(pid=400, comm="x", cmdline=["/usr/bin/x"])])
    (fake_proc / "400" / "comm").unlink()
    (fake_proc / "400" / "comm").mkdir()

    info = procfs.read_proc(fake_proc, 400)

    assert info is not None and info.pid == 400
    assert info.comm == "x", "o comm cai para o cmdline quando o arquivo some"


def test_malformed_status_fields_degrade_instead_of_raising(fake_proc):
    """Um campo malformado não pode anular a amostra dos outros."""
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[dict(pid=500, comm="x", rss_kb=1024)])
    status = fake_proc / "500" / "status"
    status.write_text(status.read_text().replace("VmRSS:\t1024 kB", "VmRSS:\tnao-é-número kB"))

    info = procfs.read_proc(fake_proc, 500)

    assert info is not None
    assert info.rss_kb == 0, "o campo malformado degrada para zero, não derruba"


def test_malformed_meminfo_line_does_not_hide_readable_fields(fake_proc):
    (fake_proc / "meminfo").write_text(
        "MemTotal:       14374304 kB\n"
        "MemAvailable:   nao-numero kB\n")
    assert procfs.read_meminfo(fake_proc) is None, "sem os dois campos, não há leitura"
