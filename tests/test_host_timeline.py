"""Incident evidence stays small, private and never invents missing values."""
import json
import stat
from dataclasses import replace

from folego.adapters import host_timeline
from folego.adapters.host_timeline import HostTimelineRecorder, read_timeline, record_snapshot
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
    assert result["samples"][-1]["mem_available_kb"] == 6_000_000
    assert len(read_timeline(folder, boot_id=BOOT)["samples"]) == 2
    assert read_timeline(folder, boot_id="../other")["quality"] == "unknown"


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


def test_timeline_rejects_new_schema_with_wrong_boot_or_electrical_quality(tmp_path):
    folder = tmp_path / 'timeline'
    HostTimelineRecorder(folder).record(_snapshot(100))
    path = folder / f'{BOOT}.jsonl'
    original = json.loads(path.read_text())
    mismatched = dict(original, boot_id='c325bc6f-a6f8-4093-8b2d-5c10008de2e5')
    bad_power = dict(original, battery_voltage_uv=8_000_000)
    unknown_schema = dict(original, schema=99)
    path.write_text('\n'.join(json.dumps(row) for row in
                      (original, mismatched, bad_power, unknown_schema)) + '\n')
    report = read_timeline(folder)
    assert report['quality'] == 'partial'
    assert len(report['samples']) == 1
    assert '3 amostra(s) ilegível(is)' in report['reason']


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
