import pytest

from deck_wellness.core import collector, sysfs


@pytest.fixture
def syszram(tmp_path):
    z = tmp_path / "block" / "zram0"
    z.mkdir(parents=True)
    # orig comp same mem_used max_comp mem_limit freed uncomp pages_comp priority
    (z / "mm_stat").write_text("4081590272 811380737 104857600 893075456 0 0 0 995723 995723 0\n")
    return tmp_path


def test_zram_mm_stat_reads_orig_comp_and_used(syszram):
    m = sysfs.read_zram_mm_stat(syszram)
    assert m.orig_data_kb == 3985928  # 4081590272 // 1024
    assert m.compr_data_kb == 792364
    assert m.mem_used_total_kb == 872144


def test_zram_missing_gives_none(tmp_path):
    assert sysfs.read_zram_mm_stat(tmp_path) is None


@pytest.fixture
def env(fake_proc, syszram, tmp_path):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[
        dict(pid=10, comm="msedge", rss_kb=2000, cmdline=["/opt/microsoft/msedge/msedge"]),
        dict(pid=11, comm="msedge", rss_kb=1000, cmdline=["/opt/microsoft/msedge/msedge", "--type=renderer"]),
        dict(pid=12, comm="msedge", rss_kb=500, cmdline=["--extension-process"]),
        dict(pid=20, comm="plasmashell", rss_kb=400),
        dict(pid=21, comm="kwin_wayland", rss_kb=100),
    ])
    return fake_proc, syszram


def test_snapshot_aggregates_memory_and_swap(env):
    proc_root, sys_root = env
    snap = collector.MetricsCollector(proc_root=proc_root, sys_root=sys_root).collect()
    assert snap.mem.mem_total_kb == 14374304
    assert snap.swap_used_kb == 3984256  # from /proc/swaps total across devices
    assert snap.errors == ()


def test_app_groups_merge_browser_renderer_processes(env):
    proc_root, sys_root = env
    snap = collector.MetricsCollector(proc_root=proc_root, sys_root=sys_root).collect()
    groups = {a.group: a for a in snap.apps}
    assert groups["edge"].rss_kb == 3500
    assert groups["edge"].procs == 3
    assert groups["plasmashell"].rss_kb == 400


def test_apps_are_sorted_desc_and_capped(env):
    proc_root, sys_root = env
    snap = collector.MetricsCollector(proc_root=proc_root, sys_root=sys_root).collect()
    rss = [a.rss_kb for a in snap.apps]
    assert rss == sorted(rss, reverse=True)
    assert snap.apps[0].group == "edge"


def test_self_rss_read_from_real_proc(env):
    proc_root, sys_root = env
    snap = collector.MetricsCollector(proc_root=proc_root, sys_root=sys_root).collect()
    assert snap.self_rss_kb > 10_000  # python itself always uses more than 10MB


def test_missing_pressure_degrades_not_crashes(fake_proc, syszram):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pressure_memory=None, meminfo=None)
    snap = collector.MetricsCollector(proc_root=fake_proc, sys_root=syszram).collect()
    assert snap.mem is None
    assert snap.pressure_memory is None
    assert "meminfo" in " ".join(snap.errors)


def test_the_collector_carries_watched_volumes_into_the_snapshot(env):
    from deck_wellness.core.tmpfs import TmpfsVolume
    proc_root, sys_root = env
    volumes = (TmpfsVolume("/tmp", "tmpfs", 8 * 1024**3, 7 * 1024**3, 1024**3),)
    snap = collector.MetricsCollector(
        proc_root=proc_root, sys_root=sys_root, tmpfs_fn=lambda root: volumes).collect()
    assert snap.tmpfs == volumes


def test_a_fake_proc_root_with_no_mounts_carries_no_tmpfs(env):
    """O collector não inventa ocupação: sem /proc/mounts não há volume medido."""
    proc_root, sys_root = env
    snap = collector.MetricsCollector(proc_root=proc_root, sys_root=sys_root).collect()
    assert snap.tmpfs == ()
