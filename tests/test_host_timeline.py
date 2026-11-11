"""Incident evidence stays small, private and never invents missing values."""
import json
import os
import stat
from dataclasses import replace

from folego.adapters import host_timeline
from folego.adapters.host_timeline import (HostTimelineRecorder, read_timeline,
                                           record_snapshot, summarize_boot_timeline)
from folego.core.snapshot import BatteryInfo, MemInfo, OK, Pressure, Snapshot, SourceQuality

BOOT = "167c36b6-b7ae-4097-877b-3ab2a96d8b88"


def _snapshot(mono: float, boot_id: str = BOOT) -> Snapshot:
    names = ("meminfo", "swaps", "pressure_memory", "pressure_io",
             "pressure_cpu", "temperature", "processes")
    return Snapshot(ts=1_793_917_000 + mono, mono=mono, boot_id=boot_id,
                    mem=MemInfo(14_000_000, 6_000_000), swap_used_kb=2_000_000,
                    swap_total_kb=7_000_000, load=None, apps=(), self_rss_kb=0,
                    pressure_memory=Pressure(0.2, 0.1, 0.0, 1),
                    pressure_io=Pressure(1.5, 0.5, 0.1, 1),
                    pressure_cpu=Pressure(2.5, 1.0, 0.2, 1),
                    temperature_c=81, temperature_sensor="acpitz",
                    sources=tuple(SourceQuality(name, OK, mono=mono) for name in names))


def test_timeline_throttles_and_preserves_private_boot_history(tmp_path):
    folder = tmp_path / "timeline"
    recorder = HostTimelineRecorder(folder)
    recorder.record(_snapshot(100))
    recorder.record(_snapshot(102))
    recorder.record(_snapshot(115))
    previous = folder / f"{BOOT}.jsonl"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE(previous.stat().st_mode) == 0o600
    assert len(previous.read_text().splitlines()) == 2
    recorder.record(_snapshot(130, "bad-boot-id"))
    assert "inválido" in recorder.last_error
    assert len(list(folder.iterdir())) == 1
    result = read_timeline(folder)
    assert result["quality"] == "ok"
    assert [row["psi_io_avg10"] for row in result["samples"]] == [1.5, 1.5]
    assert result["samples"][-1]["psi_io_avg60"] == 0.5
    assert result["samples"][-1]["psi_cpu_avg60"] == 1.0
    assert result["samples"][-1]["mem_available_kb"] == 6_000_000
    assert len(read_timeline(folder, boot_id=BOOT)["samples"]) == 2
    assert read_timeline(folder, boot_id="../other")["quality"] == "unknown"


def test_timeline_syncs_each_normal_sample_before_reporting_success(tmp_path, monkeypatch):
    folder = tmp_path / "timeline"
    recorder = HostTimelineRecorder(folder)
    durable_rows = []
    real_fsync = os.fsync

    def sync(fd):
        real_fsync(fd)
        if stat.S_ISREG(os.fstat(fd).st_mode):
            durable_rows[:] = (folder / f"{BOOT}.jsonl").read_text().splitlines()

    monkeypatch.setattr(host_timeline.os, "fsync", sync)
    assert record_snapshot(recorder, _snapshot(100)).source("host_timeline").status == OK
    assert record_snapshot(recorder, _snapshot(115)).source("host_timeline").status == OK
    # A cut immediately after the second low-pressure sample must retain it too.
    assert [json.loads(row)["mono_ns"] for row in durable_rows] == [100 * 10**9, 115 * 10**9]


def test_timeline_exposes_sync_failure_on_a_normal_sample(tmp_path, monkeypatch):
    recorder = HostTimelineRecorder(tmp_path / "timeline")
    recorder.record(_snapshot(100))

    def fail_sync(fd):
        raise OSError("sync unavailable")

    monkeypatch.setattr(host_timeline.os, "fsync", fail_sync)
    observed = record_snapshot(recorder, _snapshot(115))
    assert observed.source("host_timeline").status == "error"
    assert "sync unavailable" in observed.source("host_timeline").detail


def test_timeline_marks_corruption_unknown_and_keeps_existing_bytes(tmp_path):
    folder = tmp_path / "timeline"
    recorder = HostTimelineRecorder(folder)
    recorder.record(_snapshot(100))
    path = folder / f"{BOOT}.jsonl"
    before = path.read_bytes() + b"{broken\n"
    path.write_bytes(before)
    result = read_timeline(folder)
    assert result["quality"] == "partial" and len(result["samples"]) == 1
    assert "ilegível" in result["reason"]
    assert path.read_bytes() == before
    missing = replace(_snapshot(120), sources=())
    recorder.record(missing)
    latest = json.loads(path.read_text().splitlines()[-1])
    assert latest["mem_available_kb"] is None


def test_timeline_energy_requires_valid_sources_and_preserves_old_schema(tmp_path):
    folder = tmp_path / "timeline"
    recorder = HostTimelineRecorder(folder)
    sample = replace(_snapshot(100), battery=BatteryInfo(
                         90, 'Discharging', voltage_uv=7_694_000,
                         current_ua=1_628_000), duration_s=.042,
                     external_power_online=False,
                     sources=_snapshot(100).sources +
                     (SourceQuality('battery', OK), SourceQuality('external_power', OK)))
    observed = record_snapshot(recorder, sample)
    assert observed.source('host_timeline').status == 'ok'
    row = read_timeline(folder)['samples'][-1]
    assert row['battery_percent'] == 90
    assert row['battery_status'] == 'Discharging'
    assert row['battery_voltage_uv'] == 7_694_000
    assert row['battery_current_ua'] == 1_628_000
    assert row['battery_power_uw'] is None
    assert row['external_power_online'] is False
    assert row['schema'] == 2 and row['mono_ns'] == 100_000_000_000
    assert row['collector_read_ms'] == 42
    assert 'battery' not in row['source_issues']
    assert 'external_power' not in row['source_issues']
    unknown = replace(sample, mono=115, sources=_snapshot(115).sources)
    record_snapshot(recorder, unknown)
    row = read_timeline(folder)['samples'][-1]
    assert row['battery_percent'] is None
    assert row['battery_voltage_uv'] is None
    assert row['external_power_online'] is None
    assert row['source_issues']['battery'] == 'missing'
    assert row['source_issues']['external_power'] == 'missing'
    old = {'boot_id': BOOT, 'at': row['at']}
    assert host_timeline._valid_sample(old)
    with (folder / f'{BOOT}.jsonl').open('a') as stream:
        stream.write(json.dumps(old) + '\n')
    historical = read_timeline(folder)['samples'][-1]
    assert historical == old  # no electrical or source-quality proof invented


def test_timeline_syncs_the_first_critical_reading_and_power_edges(tmp_path, monkeypatch):
    folder = tmp_path / "timeline"
    recorder = HostTimelineRecorder(folder)
    synced = []
    real_fsync = os.fsync

    def sync(fd):
        if stat.S_ISREG(os.fstat(fd).st_mode):
            synced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(host_timeline.os, "fsync", sync)

    def observe(mono, online, voltage, *, valid=True):
        snapshot = _snapshot(mono)
        status = "Charging" if online else "Discharging"
        extra_sources = (SourceQuality("battery", OK), SourceQuality("external_power", OK))
        recorder.record(replace(snapshot,
                                sources=snapshot.sources + (extra_sources if valid else ()),
                                external_power_online=online,
                                battery=BatteryInfo(54, status, voltage_uv=voltage,
                                                    voltage_min_design_uv=7_700_000)))

    observe(100, True, 8_500_000)
    observe(102, False, 6_500_000, valid=False)
    observe(105, False, 6_560_000)
    observe(106, False, 6_510_000)
    observe(107, False, 7_050_000)  # still in attention, so the episode stays open
    observe(108, False, 6_560_000)
    observe(109, False, 7_500_000)  # valid recovery rearms even between writes
    observe(110, False, 6_620_000)
    observe(111, True, 8_500_000)
    observe(126, True, 8_500_000)

    report = read_timeline(folder)
    assert report["quality"] == "ok"
    assert [row["mono_ns"] // 10**9 for row in report["samples"]] == [100, 105, 110, 111, 126]
    assert [row.get("power_events", []) for row in report["samples"]] == [
        [], ["battery-voltage-critical", "external-power-disconnected"],
        ["battery-voltage-critical"], ["external-power-connected"], [],
    ]
    assert len(synced) == 5  # every recorded sample, including the three power events
    critical = report["samples"][1]
    assert critical["battery_voltage_uv"] == 6_560_000
    assert critical["battery_voltage_min_design_uv"] == 7_700_000
    summary = summarize_boot_timeline(folder, BOOT)
    assert summary["last_power_event"]["power_events"] == ["external-power-connected"]
    assert summary["last"]["power_events"] is None


def test_timeline_rejects_new_schema_with_wrong_boot_or_electrical_quality(tmp_path):
    folder = tmp_path / 'timeline'
    HostTimelineRecorder(folder).record(_snapshot(100))
    path = folder / f'{BOOT}.jsonl'
    original = json.loads(path.read_text())
    mismatched = dict(original, boot_id='c325bc6f-a6f8-4093-8b2d-5c10008de2e5')
    bad_power = dict(original, battery_voltage_uv=8_000_000)
    unsupported_event = dict(original, power_events=["external-power-disconnected"])
    unknown_schema = dict(original, schema=99)
    path.write_text('\n'.join(json.dumps(row) for row in
                      (original, mismatched, bad_power, unsupported_event, unknown_schema)) + '\n')
    report = read_timeline(folder)
    assert report['quality'] == 'partial'
    assert len(report['samples']) == 1
    assert '4 amostra(s) ilegível(is)' in report['reason']


def test_timeline_limit_is_visible_and_write_failure_reaches_snapshot(tmp_path, monkeypatch):
    folder = tmp_path / "timeline"
    recorder = HostTimelineRecorder(folder)
    recorder.record(_snapshot(100))
    path = folder / f"{BOOT}.jsonl"
    original = path.read_bytes()
    monkeypatch.setattr(host_timeline, '_PER_BOOT_LIMIT', len(original))
    report = read_timeline(folder, active_boot_id=BOOT)
    assert report['quality'] == 'ok'
    assert report['capacity']['at_limit'] is True
    assert report['capacity']['near_limit'] is True
    observed = record_snapshot(recorder, _snapshot(115))
    assert observed.source('host_timeline').status == 'error'
    assert 'cheio' in observed.source('host_timeline').detail
    assert path.read_bytes() == original


def test_capacity_warns_before_history_stops_without_rotating_any_bytes(tmp_path, monkeypatch):
    folder = tmp_path / "timeline"
    recorder = HostTimelineRecorder(folder)
    recorder.record(_snapshot(100))
    path = folder / f"{BOOT}.jsonl"
    original = path.read_bytes()
    monkeypatch.setattr(host_timeline, '_PER_BOOT_LIMIT', len(original) * 100 // 90)
    report = read_timeline(folder, active_boot_id=BOOT)
    assert report['capacity']['near_limit'] is True
    assert report['capacity']['at_limit'] is False
    assert path.read_bytes() == original


def test_boot_summary_bounds_read_and_marks_absent_boot_unknown(tmp_path):
    folder = tmp_path / 'timeline'
    recorder = HostTimelineRecorder(folder)
    recorder.record(_snapshot(100))
    recorder.record(_snapshot(115))
    path = folder / f'{BOOT}.jsonl'
    # Enough valid rows to cross the 64 KiB window without writing to the host.
    original = path.read_bytes().splitlines()
    path.write_bytes((original[0] + b'\n') * 170 + original[1] + b'\n')
    summary = summarize_boot_timeline(folder, BOOT)
    assert summary['quality'] == 'ok'
    assert summary['window_limited'] is True
    assert summary['last']['mono_ns'] == 115_000_000_000
    assert summary['last']['psi_mem_avg60'] == 0.1
    assert summary['recent_max_interval_s'] == 15
    assert summary['recent_samples'] == 80
    assert summarize_boot_timeline(folder, 'c325bc6f-a6f8-4093-8b2d-5c10008de2e5')[
        'quality'] == 'missing'


def test_boot_summary_keeps_invalid_last_line_visible(tmp_path):
    folder = tmp_path / 'timeline'
    HostTimelineRecorder(folder).record(_snapshot(100))
    path = folder / f'{BOOT}.jsonl'
    with path.open('ab') as stream:
        stream.write(b'{interrupted\n')
    summary = summarize_boot_timeline(folder, BOOT)
    assert summary['quality'] == 'partial'
    assert summary['last']['mono_ns'] == 100_000_000_000
    assert 'ilegível' in summary['reason']


def test_boot_summary_never_calls_an_incomplete_tail_empty(tmp_path):
    folder = tmp_path / 'timeline'
    HostTimelineRecorder(folder).record(_snapshot(100))
    path = folder / f'{BOOT}.jsonl'
    path.write_bytes(b'x' * 70000 + b'\n')
    summary = summarize_boot_timeline(folder, BOOT)
    assert summary['quality'] == 'unknown'
    assert summary['last'] is None
    assert 'sem linha completa' in summary['reason']
