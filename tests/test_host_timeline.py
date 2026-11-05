"""Incident evidence stays small, private and never invents missing values."""
import json
import stat
from dataclasses import replace

from folego.adapters.host_timeline import HostTimelineRecorder, read_timeline
from folego.core.snapshot import MemInfo, OK, Pressure, Snapshot, SourceQuality

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
