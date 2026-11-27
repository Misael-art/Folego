"""Cooperating agents keep their sessions and account for missing measurements."""
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from folego.actions import workload
from folego.core.agents import footprint
from folego.core.sessions import SessionRegistry, SessionError
from folego.core.workload_history import summarize
from test_agent_footprint import proc
from test_host_timeline import BOOT, _snapshot


def test_partial_io_is_never_a_zero_or_a_complete_total():
    a = replace(proc(10, "claude"), io_write_bps=0, io_read_bps=3)
    b = replace(proc(11, "node", ppid=10), io_read_bps=4)
    agents = footprint([a, b])
    assert agents["claude"]["io_read_bps"] == 7
    assert agents["claude"]["io_write_bps"] == 0
    assert agents["claude"]["io_write_measured"] == 1
    report = summarize([{"agents": agents}, {}])["agents"]["claude"]
    assert report["io_write_bps"]["samples"] == 0
    assert report["io_read_bps"]["p95"] == 7


def test_gate_blocks_two_launchers_and_preserves_members(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    with workload._reservation():
        with pytest.raises(SessionError, match="Outra solicitação"):
            with workload._reservation():
                pytest.fail("concurrent admission")
    item = dict(schema=1, pid=10, starttime=22, namespace=81, boot_id=BOOT, session_id=BOOT)
    workload.save_object(workload._state(), item)
    survivor = replace(proc(12, "bash"), session=10)
    snapshot = replace(_snapshot(100), procs=(survivor,))
    assert workload._previous(snapshot, 81)["state"] == "membros após saída do líder"
    assert workload._previous(snapshot, 82)["state"] == "inventário incerto"
    assert workload._previous(replace(snapshot, procs=()), 81)["state"] == "sessão liberada"


def test_lost_launcher_before_commit_cannot_start_command(tmp_path):
    reader, writer = os.pipe()
    target = tmp_path / "unexpected"
    with subprocess.Popen([sys.executable, "-m", "folego.process.job_child", "--admission-fd", str(reader), "missing.json", "--",
                           "touch", str(target)], pass_fds=(reader,)) as child:
        os.close(reader)
        os.close(writer)
        assert child.wait(timeout=5) != 0
    assert not target.exists()


def test_committed_command_runs_under_registered_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(workload, "capacity", lambda *a: {"decision": "ready", "namespace": 123, "observed_mono": time.monotonic()})
    monkeypatch.setenv("FOLEGO_JOB_ROOT", str(tmp_path / "jobs"))
    dest = tmp_path / "pid"
    args = SimpleNamespace(ram_mib=10, disk_mib=1, destination=".", project="", label="QA")
    child, session, manifest = workload.launch(args, [sys.executable, "-c",
        "import os,sys;open(sys.argv[1],'w').write(str(os.getpid()))", str(dest)], SessionRegistry())
    assert child.wait(timeout=5) == 0
    assert int(dest.read_text()) == session.pid == child.pid
    from folego.safely.jobtemp import finish_job
    assert finish_job(manifest, child.pid, certain=True)
    assert session.keep_active and workload.read_object(workload._state())["session_id"] == session.session_id


def test_capacity_checks_estimates_pressure_and_partial_sources(tmp_path, monkeypatch):
    from folego.core.snapshot import MemInfo
    root = tmp_path / "proc"
    (root / "1").mkdir(parents=True)
    (root / "1/comm").write_text("systemd\n")
    (root / "self/ns").mkdir(parents=True)
    (root / "self/ns/pid").touch()
    (root / "vmstat").write_text("pswpin 0\npswpout 0\n")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("DECKWELLNESS_PROC_ROOT", str(root))
    monkeypatch.setenv("DECKWELLNESS_SYS_ROOT", str(tmp_path / "sys"))
    monkeypatch.setattr(workload.time, "sleep", lambda _: None)
    monkeypatch.setattr(workload, "read_mounts_checked", lambda: ((("/", "btrfs"),), None))
    monkeypatch.setattr(workload, "_free_mib", lambda *args: 15000)
    snap = replace(_snapshot(5), thermal_passive_c=100, mem=MemInfo(16*1024**2, 8*1024**2))
    monkeypatch.setattr(workload, "MetricsCollector", lambda: SimpleNamespace(collect=lambda: snap))
    assert workload.capacity(2048, 256, tmp_path)["decision"] == "ready"
    assert workload.capacity(5000, 256, tmp_path)["decision"] == "wait"
    assert workload.capacity(10, 5000, tmp_path)["decision"] == "wait"
    snap = replace(snap, pressure_memory=None, temperature_c=None)
    assert workload.capacity(10, 0, tmp_path)["decision"] == "unknown"


def test_capacity_waits_after_a_recent_spike_hidden_by_a_cool_reading(tmp_path, monkeypatch):
    from folego.adapters.host_timeline import HostTimelineRecorder
    from folego.core.snapshot import MemInfo
    from folego import paths
    root = tmp_path / "proc"
    (root / "1").mkdir(parents=True)
    (root / "1/comm").write_text("systemd\n")
    (root / "self/ns").mkdir(parents=True)
    (root / "self/ns/pid").touch()
    (root / "vmstat").write_text("pswpin 0\npswpout 0\n")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("DECKWELLNESS_PROC_ROOT", str(root))
    monkeypatch.setenv("DECKWELLNESS_SYS_ROOT", str(tmp_path / "sys"))
    monkeypatch.setattr(workload.time, "sleep", lambda _: None)
    monkeypatch.setattr(workload, "read_mounts_checked", lambda: ((("/", "btrfs"),), None))
    monkeypatch.setattr(workload, "_free_mib", lambda *args: 15000)
    base = replace(_snapshot(1000), procs=(), thermal_passive_c=100,
                   mem=MemInfo(16 * 1024 ** 2, 8 * 1024 ** 2))
    snap = replace(base, mono=1200, temperature_c=59)
    monkeypatch.setattr(workload, "MetricsCollector", lambda: SimpleNamespace(collect=lambda: snap))
    assert workload.capacity(10, 0, tmp_path)["decision"] == "ready"  # no history: instant reading
    recorder = HostTimelineRecorder(paths.host_timeline_dir())
    recorder.record(replace(base, temperature_c=95))
    recorder.record(replace(base, mono=1020, temperature_c=61))
    result = workload.capacity(10, 0, tmp_path)
    assert result["decision"] == "wait"
    assert any("Pico térmico recente de 95" in reason for reason in result["reasons"])
    snap = replace(base, mono=1000 + workload.THERMAL_RECENT_S + 30, temperature_c=59)
    assert workload.capacity(10, 0, tmp_path)["decision"] == "ready"
    (paths.host_timeline_dir() / f"{base.boot_id}.jsonl").chmod(0o644)
    result = workload.capacity(10, 0, tmp_path)
    assert result["decision"] == "unknown"
    assert "Histórico térmico recente ilegível" in result["reasons"]


def test_scope_cpu_requires_same_cgroup_identity_and_monotonic_window(tmp_path, monkeypatch):
    from folego.adapters.workload_scopes import WorkloadScopes
    monkeypatch.setenv("DECKWELLNESS_SYS_ROOT", str(tmp_path))
    prefix = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/app.slice"
    group = tmp_path / "fs/cgroup" / prefix / "folego-accessibility.service"
    group.mkdir(parents=True)
    (group / "memory.current").write_text("4096")
    (group / "cpu.stat").write_text("usage_usec 10000\n")
    scopes = WorkloadScopes()
    assert scopes.sample(_snapshot(50))[0]["cpu_pct"] is None
    (group / "cpu.stat").write_text("usage_usec 6010000\n")
    row, = scopes.sample(_snapshot(110))
    assert row["cpu_pct"] == 10 and row["memory_bytes"] == 4096
    assert scopes.sample(_snapshot(500))[0]["cpu_pct"] is None
