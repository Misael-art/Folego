"""Host guards use bounded evidence and never turn a gap into healthy."""
import json
import time

from folego.adapters.host_guard import HostObserver, _boots, _ntfs_events
from folego.adapters.host_timeline import HostTimelineRecorder
from folego.core.host_guard import PressureAlertTracker, ThermalTracker
from folego.core.snapshot import ERROR, OK, MemInfo, Pressure, Snapshot, SourceQuality
from folego.core.sysfs import read_thermal_trips

BOOT = "167c36b6-b7ae-4097-877b-3ab2a96d8b88"


def _pressure_sample(mono, *, cpu=30, memory=None, io=None, status=OK, boot_id=BOOT):
    sources = [SourceQuality("pressure_cpu", status)]
    if memory is not None:
        sources.append(SourceQuality("pressure_memory", OK))
    if io is not None:
        sources.append(SourceQuality("pressure_io", OK))
    return Snapshot(ts=1_700_000_000 + mono, mono=mono, boot_id=boot_id,
                    mem=None, swap_used_kb=0, swap_total_kb=0,
                    pressure_memory=Pressure(memory, memory, memory, 0) if memory is not None else None,
                    pressure_io=Pressure(io, io, io, 0) if io is not None else None,
                    pressure_cpu=Pressure(cpu, cpu, cpu, 0), load=None,
                    apps=(), self_rss_kb=0,
                    sources=tuple(sources))


def test_pressure_alert_requires_fresh_continuous_source_and_bounds_repetition():
    tracker = PressureAlertTracker()
    assert tracker.observe(_pressure_sample(100), now_mono=100) is None
    assert tracker.observe(_pressure_sample(110), now_mono=110) is None
    alert = tracker.observe(_pressure_sample(115), now_mono=115)
    assert alert["kind"] == "cpu" and alert["source"] == "pressure_cpu"
    assert alert["value"] == 30 and alert["window_s"] == 60
    assert tracker.observe(_pressure_sample(120), now_mono=120) is None
    assert tracker.observe(_pressure_sample(415), now_mono=415) is None  # gap
    assert tracker.observe(_pressure_sample(430), now_mono=430) is not None


def test_pressure_alert_unknown_and_recovery_never_bypass_repeat_limit():
    tracker = PressureAlertTracker()
    tracker.observe(_pressure_sample(100), now_mono=100)
    assert tracker.observe(_pressure_sample(115), now_mono=115)
    assert tracker.observe(_pressure_sample(130, status=ERROR), now_mono=130) is None
    assert tracker.observe(_pressure_sample(145), now_mono=145) is None
    assert tracker.observe(_pressure_sample(160), now_mono=160) is None
    assert tracker.observe(_pressure_sample(175, cpu=10), now_mono=175) is None
    assert tracker.observe(_pressure_sample(190, cpu=10), now_mono=190) is None
    assert tracker.observe(_pressure_sample(205), now_mono=205) is None
    assert tracker.observe(_pressure_sample(220), now_mono=220) is None
    assert tracker.observe(_pressure_sample(235), now_mono=260) is None  # stale
    other = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert tracker.observe(_pressure_sample(240, boot_id=other), now_mono=240) is None
    assert tracker.observe(_pressure_sample(255, boot_id=other), now_mono=255)


def test_pressure_alert_combines_simultaneous_sources_without_popup_burst():
    tracker = PressureAlertTracker()
    tracker.observe(_pressure_sample(100, memory=6, io=12), now_mono=100)
    alert = tracker.observe(_pressure_sample(115, memory=6, io=12), now_mono=115)
    assert alert['kind'] == 'memory'
    assert alert['also'] == [{'kind': 'io', 'value': 12},
                             {'kind': 'cpu', 'value': 30}]
    assert tracker.observe(_pressure_sample(120, memory=6, io=12), now_mono=120) is None


def _host(tmp_path, *, mounts=1):
    proc = tmp_path / "proc"
    sys = tmp_path / "sys"
    (proc / "self").mkdir(parents=True)
    (proc / "sys/kernel/random").mkdir(parents=True)
    (proc / "sys/kernel/random/boot_id").write_text(BOOT + "\n")
    lines = ["36 25 0:28 / / rw - btrfs /dev/nvme0n1p2 rw"]
    lines.extend(f"40 25 0:30 / /mnt/card{i} rw - fuseblk /dev/mmcblk{i}p1 rw"
                 for i in range(mounts))
    (proc / "self/mountinfo").write_text("\n".join(lines) + "\n")
    stats = sys / "fs/btrfs/307f0ecc-3ad9-4619-893d-28454cad339a/devinfo/1/error_stats"
    stats.parent.mkdir(parents=True)
    stats.write_text("write_errs 0\nread_errs 0\nflush_errs 0\ncorruption_errs 6741\ngeneration_errs 0\n")
    return proc, sys, stats


def _run(argv, timeout):
    assert timeout <= 3
    if argv[0] == "systemctl" and "list-units" in argv:
        return 0, "codex-quota-panel.service loaded activating auto-restart\n", ""
    if argv[0] == "systemctl":
        return 0, "NRestarts=403\nActiveState=activating\nSubState=auto-restart\nResult=exit-code\n", ""
    if "--list-boots" in argv:
        return 0, ("IDX BOOT ID FIRST LAST\n"
                   " -1 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa Wed yesterday\n"
                   "  0 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb Thu today\n"), ""
    if "journalctl" == argv[0] and "-o" in argv and "json" in argv and "-n" in argv and "1" in argv:
        return 0, json.dumps({"__REALTIME_TIMESTAMP": "1700000010000000",
                              "__MONOTONIC_TIMESTAMP": "120000000"}), ""
    if "systemd-logind.service" in argv:
        return 1, "", ""
    if "-g" in argv:
        assert "Corrupt index block signature" in argv[argv.index("-g") + 1]
        return 0, "\n".join(json.dumps({"MESSAGE": message,
                                        "__REALTIME_TIMESTAMP": "1000000000"})
                            for message in (
                                "ntfs_mst_post_read_fixup_warn",
                                "Corrupt index block signature: vcn 3 inode 382656")) + "\n", ""
    raise AssertionError(argv)


def test_btrfs_baseline_preserves_history_and_reports_new_errors(tmp_path):
    proc, sys, stats = _host(tmp_path)
    state = tmp_path / "state/host-guard.json"
    observer = HostObserver(proc_root=proc, sys_root=sys, state_path=state,
                            run=_run, record=True, clock=lambda: 1000)
    first = observer.observe()
    assert first["btrfs"][0]["trend"] == "unknown"
    assert state.exists()
    stats.write_text(stats.read_text().replace("corruption_errs 6741", "corruption_errs 6742"))
    second = observer.observe()
    assert second["btrfs"][0]["delta"]["corruption_errs"] == 1
    assert second["btrfs"][0]["recent_delta"]["corruption_errs"] == 1
    third = observer.observe()
    assert third["btrfs"][0]["trend"] == "stable"
    assert third["btrfs"][0]["recent_delta"]["corruption_errs"] == 1
    assert third["ntfs"]["count_10m"] == 2
    assert third["ntfs"]["index_inodes_10m"] == 1
    assert third["ntfs"]["index_blocks_10m"] == 1
    assert third["ntfs"]["mount"]["mount"] == "/mnt/card0"
    assert third["services"]["items"][0]["restarts"] == 403
    assert third["boots"]["previous_end"] == "inconclusive"
    assert third["boots"]["items"][0]["end"] == "inconclusive"


def test_corrupt_baseline_is_preserved_and_ambiguous_ntfs_is_not_attributed(tmp_path):
    proc, sys, _ = _host(tmp_path, mounts=2)
    state = tmp_path / "host-guard.json"
    state.write_text("{broken")
    before = state.read_bytes()
    result = HostObserver(proc_root=proc, sys_root=sys, state_path=state,
                          run=_run, record=True, clock=lambda: 1000).observe()
    assert result["baseline_quality"] == "unknown"
    assert result["btrfs"][0]["delta"] is None
    assert result["ntfs"]["mount"] is None
    assert state.read_bytes() == before


def test_stale_timeline_keeps_capacity_and_reports_missing_interval(tmp_path):
    proc, sys, _ = _host(tmp_path)
    folder = tmp_path / 'timeline'
    HostTimelineRecorder(folder).record(Snapshot(
        ts=1_700_000_000, mono=100, boot_id=BOOT, mem=None, swap_used_kb=0,
        swap_total_kb=0, pressure_memory=None, pressure_io=None,
        pressure_cpu=None, load=None, apps=(), self_rss_kb=0))
    result = HostObserver(proc_root=proc, sys_root=sys, timeline_dir=folder,
                          state_path=tmp_path / 'state.json', run=_run,
                          clock=lambda: 1_700_000_300).observe()
    assert result['timeline']['quality'] == 'stale'
    assert result['timeline']['last_boot_id'] == BOOT
    assert result['timeline']['capacity']['active_boot_bytes'] > 0


def test_boot_history_includes_bounded_local_evidence_and_missing_boot(tmp_path):
    proc, sys, _ = _host(tmp_path)
    folder = tmp_path / 'timeline'
    previous = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    HostTimelineRecorder(folder).record(Snapshot(
        ts=1_700_000_000, mono=100, boot_id=previous, mem=None, swap_used_kb=0,
        swap_total_kb=0, pressure_memory=None, pressure_io=None,
        pressure_cpu=None, load=None, apps=(), self_rss_kb=0))
    observer = HostObserver(proc_root=proc, sys_root=sys, timeline_dir=folder,
                            state_path=tmp_path / 'state.json', run=_run,
                            clock=lambda: 1_700_000_300)
    report = observer.observe()
    assert report['boots']['items'][0]['timeline']['quality'] == 'ok'
    assert report['boots']['items'][0]['timeline']['last']['at']
    assert report['boots']['items'][0]['sample_to_journal_s'] == 20
    assert report['boots']['items'][0]['gap_clock'] == 'monotonic'
    assert report['boots']['items'][0]['journal_tail']['quality'] == 'ok'
    assert report['timeline']['quality'] == 'missing'  # current boot has no file
    assert report['observer_duration_ms'] >= 0

    (folder / f'{previous}.jsonl').unlink()  # disposable fixture only
    refreshed = HostObserver(proc_root=proc, sys_root=sys, timeline_dir=folder,
                             state_path=tmp_path / 'state.json', run=_run,
                             clock=lambda: 1_700_000_300).observe()
    assert refreshed['boots']['items'][0]['timeline']['quality'] == 'missing'
    assert refreshed['boots']['items'][0]['timeline']['last'] is None


def test_malformed_ntfs_journal_does_not_create_a_safe_count():
    mounts = [{"mount": "/mnt/card", "source": "/dev/mmcblk0p1", "type": "fuseblk"}]
    for payload in ("[]\n", '{"MESSAGE":"Corrupt index block signature: vcn 0 inode 1"}\n'):
        result = _ntfs_events(lambda argv, timeout: (0, payload, ""), mounts)
        assert result["quality"] == "unknown"
        assert result["count_10m"] is None


def test_boot_history_finds_logind_poweroff_beyond_noisy_tail():
    def run(argv, timeout):
        assert timeout <= 3
        if "--list-boots" in argv:
            return 0, (" -2 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa Wed earlier\n"
                       " -1 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb Thu previous\n"
                       "  0 cccccccccccccccccccccccccccccccc Thu current\n"), ""
        assert "systemd-logind.service" in argv and "-g" in argv
        assert "40" not in argv
        if "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" in argv:
            return 0, "System is powering down.\n", ""
        return 1, "", ""

    result = _boots(run)
    assert result["quality"] == "ok"
    assert [item["end"] for item in result["items"][:-1]] == [
        "inconclusive", "shutdown_recorded"]
    assert result["previous_end"] == "shutdown_recorded"
    assert "1 boot anterior" in result["reason"]


def test_thermal_guard_uses_only_matching_acpi_limits_and_fresh_samples(tmp_path):
    zone = tmp_path / "class/thermal/thermal_zone0"
    zone.mkdir(parents=True)
    (zone / "type").write_text("acpitz")
    (zone / "trip_point_0_type").write_text("critical")
    (zone / "trip_point_0_temp").write_text("105000")
    (zone / "trip_point_1_type").write_text("passive")
    (zone / "trip_point_1_temp").write_text("100000")
    assert read_thermal_trips(tmp_path, "acpitz") == (100, 105)
    assert read_thermal_trips(tmp_path, "k10temp") == (None, None)
    base = dict(ts=1000, mem=MemInfo(1000, 500), swap_used_kb=0,
                swap_total_kb=0, pressure_memory=None, pressure_io=None,
                pressure_cpu=None, load=None, apps=(), self_rss_kb=0,
                boot_id="boot-1", temperature_sensor="acpitz",
                thermal_passive_c=100, thermal_critical_c=105)
    tracker = ThermalTracker()
    now = time.monotonic()
    hot = tracker.observe(Snapshot(**base, mono=now, temperature_c=97))
    cool = tracker.observe(Snapshot(**base, mono=now + 30, temperature_c=81))
    assert hot["state"] == "high"
    assert cool["peak_c"] == 97 and cool["current_c"] == 81
    assert cool["state"] == "recent_high"
    assert tracker.observe(Snapshot(**base, mono=now + 32, temperature_c=100))["state"] == "danger"
    assert tracker.observe(Snapshot(**base, mono=now + 33, temperature_c=105))["state"] == "critical"
    missing = tracker.observe(Snapshot(**base, mono=now + 34, temperature_c=None))
    assert missing["state"] == "unknown" and missing["current_c"] is None
    failed = tracker.observe(Snapshot(**base, mono=now + 35, temperature_c=105,
                                      sources=(SourceQuality("temperature", ERROR),)))
    assert failed["state"] == "unknown"
