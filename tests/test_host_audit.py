"""Auditor records evidence without inferring removals from failed reads."""
from contextlib import closing
from dataclasses import replace
import json
import os
import sqlite3
from types import SimpleNamespace

import pytest

from folego import audit_profile, cli
from folego.actions.accessibility_recovery import Recovery
from folego.actions.performance import auto
from folego.adapters import host_audit as audit
from folego.core.instance import InstanceLock
from folego.core.perf_rules import ConditionTracker
from folego.core.snapshot import BatteryInfo, SourceQuality
from test_host_timeline import BOOT, _snapshot


@pytest.fixture(autouse=True)
def audit_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def test_profile_cli_switches_persistently_and_unknown_protects(tmp_path, capsys):
    assert cli.main(["audit", "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["enabled"] is False
    assert cli.main(["audit", "enable", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["enabled"] is True
    with audit_profile.normal_effects() as allowed:
        assert not allowed
    assert cli.main(["audit", "disable"]) == 0
    with audit_profile.normal_effects() as allowed:
        assert allowed
    path = tmp_path / "config/folego/audit-profile.json"
    path.write_text('{"schema":99,"enabled":false}')
    assert cli.main(["audit", "enable"]) != 0
    assert '"schema":99' in path.read_text()
    assert not audit_profile.normal()


def test_auditor_preserves_input_and_pauses_performance():
    assert audit_profile.configure(True)["ok"]
    collector = SimpleNamespace(collect=lambda: pytest.fail("performance should not run"))
    report = auto.cycle(collector=collector, tracker=ConditionTracker(), store=None, rules_path=None)
    assert report["trigger"] == "audit"
    recovery = Recovery(SimpleNamespace(), backend=object())
    with pytest.raises(ValueError, match="Modo Auditor"):
        recovery.prepare("microphone")
    with pytest.raises(ValueError, match="Modo Auditor"):
        recovery.prepare("all", save=True)
    class InputSeen(Exception):
        pass

    def observe_input():
        raise InputSeen

    recovery.supervisor.native = SimpleNamespace(collect=observe_input)
    with pytest.raises(InputSeen):
        recovery.prepare("virtual-keyboard")
    with pytest.raises(InputSeen):
        recovery.prepare("gamepad")


def test_inventory_keeps_good_baseline_over_failures_and_boots():
    def unavailable(_):
        raise OSError("temporarily unreadable")

    other_boot = "00000000-0000-0000-0000-000000000001"
    with audit._connect(write=True) as db:
        audit._record_source(db, BOOT, 1000, "packages", lambda _: {"mesa": "1", "tools": "2"})
        audit._record_source(db, BOOT, 1300, "packages", unavailable)
        audit._record_source(db, other_boot, 1600, "packages",
                             lambda _: {"mesa": "3", "new-tool": "1"})
    results = audit.history(source="packages", boot=other_boot)
    changes = {e["subject"]: e for e in results["events"] if e["kind"] != "source"}
    assert changes["mesa"]["kind"] == "changed"
    assert changes["mesa"]["data"]["before"] == "1"
    assert changes["mesa"]["data"]["after"] == "3"
    assert changes["tools"]["kind"] == "removed"
    assert changes["new-tool"]["kind"] == "added"
    assert changes["tools"]["data"]["last_observed_boot"] == BOOT
    assert changes["tools"]["data"]["last_observed_at"] == audit._iso(1000)
    first = audit.history(boot=BOOT)["events"]
    assert [e["kind"] for e in first] == ["baseline", "source"]
    assert first[1]["data"]["quality"] == "unknown"
    assert os.stat(audit._database()).st_mode & 0o777 == 0o600
    latest = audit.history(limit=2)
    page = audit.history(limit=5, before_id=latest["events"][0]["id"])
    assert latest["limited"]
    assert len(page["events"]) == 4
    assert {e["id"] for e in page["events"]}.isdisjoint(e["id"] for e in latest["events"])


def test_journal_deduplicates_and_drops_message_body(monkeypatch):
    row = {"__CURSOR": "cursor", "__REALTIME_TIMESTAMP": "1000000000",
           "_BOOT_ID": BOOT.replace("-", ""), "_TRANSPORT": "kernel",
           "PRIORITY": "3", "MESSAGE": "Out of memory: sensitive host data"}
    monkeypatch.setattr(audit, "_query",
                        lambda *args: SimpleNamespace(stdout=json.dumps(row) + "\n", stderr=""))
    with audit._connect(write=True) as db:
        for ts in (1000, 1001):
            audit._record_source(db, BOOT, ts, "journal",
                                 lambda since: audit._journal(BOOT, ts, since, crash=False), journal=True)
    events = audit.history()["events"]
    assert len(events) == 1
    assert events[0]["data"]["category"] == "memória esgotada"
    assert "sensitive" not in json.dumps(events)


def test_recorder_keeps_voltage_and_metrics_at_a_bounded_cadence(monkeypatch):
    for name in ("_mounts", "_disks", "_disk_capacity", "_packages", "_flatpak", "_services"):
        monkeypatch.setattr(audit, name, lambda *args, **kwargs: {})
    monkeypatch.setattr(audit, "_journal", lambda *args, **kwargs: ([], ""))
    recorder = audit.HostAuditRecorder()
    recorder.record(_snapshot(100))
    assert audit.history()["quality"] == "missing"
    assert audit_profile.configure(True)["ok"]
    for mono in (100, 115, 160):
        snapshot = _snapshot(mono)
        recorder.record(replace(snapshot, battery=BatteryInfo(55, "Discharging", voltage_uv=7200000),
                                sources=(*snapshot.sources, SourceQuality("battery", "ok"))))
    report = audit.history(source="metrics")
    assert not recorder.error
    assert [event["data"]["mono_ns"] for event in report["events"]] == [100 * 10**9, 160 * 10**9]
    assert report["events"][-1]["data"]["battery_voltage_uv"] == 7200000
    assert report["events"][-1]["data"]["temperature_c"] == 81
    with closing(sqlite3.connect(audit._database())) as db:
        db.execute("PRAGMA user_version=2")
    assert audit.history()["quality"] == "unknown"


def test_cli_watcher_refuses_a_second_writer(capsys):
    assert audit_profile.configure(True)["ok"]
    with InstanceLock():
        assert cli.main(["audit", "watch", "--json"]) != 0
    assert "instância do Fôlego" in capsys.readouterr().out
    assert audit.history()["quality"] == "missing"
