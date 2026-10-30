"""Portable host matrix and failures; no real input mutations or captures."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from folego.adapters.accessibility import NativeInput, bounded_command
from folego.actions import accessibility as action
from folego.actions.accessibility_service import install, watch, UNIT
from folego.core.accessibility import parse_devices
from folego.orchestration import Coordinator
from folego.orchestration.journal import Journal
from folego.orchestration.models import Outcome

KEY = "a" * 64


def report(enabled=False):
    return {"schema": 1, "mono": time.monotonic(), "boot_id": "boot", "backend": "kwin",
        "service_owner": ":1.23", "errors": [], "blockers": [], "providers": [], "cards": [],
        "devices": [{"key": KEY, "event": "event3", "name": "Keyboard", "enabled": enabled,
                     "repairable": True, "stable": True, "kinds": ["keyboard"]}]}


class Native:
    qdbus = "fake-qdbus"
    clock = staticmethod(time.monotonic)
    def __init__(self, enabled=False):
        self.report = report(enabled)
        self.calls = []
        self.fail = False
        self.hook = lambda: None

    def collect(self):
        value = copy.deepcopy(self.report)
        value["mono"] = time.monotonic()
        return value

    def call(self, argv):
        self.hook()
        assert argv[-2:] == ["enabled", "true"]
        self.calls.append(argv)
        self.report["devices"][0]["enabled"] = True
        if self.fail:
            from folego.adapters.accessibility import ProbeError
            raise ProbeError("response lost after effect")
        return ""


@pytest.fixture
def supervisor(tmp_path, fake_home):
    return action.Supervisor(native=Native(), store=action.Store(tmp_path / "state"),
        coordinator=Coordinator(journal=Journal(tmp_path / "journal"), lock_path=tmp_path / "coordinator"))


def test_native_repair_without_phasezero_has_durable_intent_and_replays_same_id(supervisor):
    plan = action.plans(supervisor.inspect())[0]
    supervisor.native.hook = lambda: assert_intent(supervisor, plan.operation_id)
    assert supervisor.repair(plan, confirm=False).outcome == Outcome.REFUSED
    for _ in range(2):
        result = supervisor.repair(plan, confirm=True)
        assert result.outcome == Outcome.OK and result.operation_id == plan.operation_id
    assert len(supervisor.native.calls) == 1
    assert [row.kind for row in supervisor.coordinator.journal.records()] == ["intent", "result"]


def assert_intent(supervisor, operation_id):
    state = supervisor.coordinator.journal.state_of(operation_id)
    assert state.intent is not None and state.result is None


@pytest.mark.parametrize("change", ["event", "boot_id", "service_owner", "blocker"])
def test_changed_identity_or_external_owner_refuses_before_effect(supervisor, change):
    plan = action.plans(supervisor.inspect())[0]
    if change == "event":
        supervisor.native.report["devices"][0]["event"] = "event8"
    elif change == "blocker":
        supervisor.native.report["blockers"] = ["another application repairing"]
    else:
        supervisor.native.report[change] = "changed"
    assert supervisor.repair(plan, confirm=True).outcome == Outcome.REFUSED
    assert supervisor.native.calls == []


def test_timeout_keeps_effect_unknown_until_explicit_observation(supervisor):
    plan = action.plans(supervisor.inspect())[0]
    supervisor.native.fail = True
    result = supervisor.repair(plan, confirm=True)
    assert result.outcome == Outcome.UNKNOWN and supervisor.store.read()["circuit"]
    assert supervisor.inspect()["pending_operations"] == [plan.operation_id]
    assert supervisor.repair(plan, confirm=True).outcome == Outcome.UNKNOWN
    assert len(supervisor.native.calls) == 1
    with pytest.raises(ValueError, match="pendente"):
        supervisor.configure(rearm=True)
    assert supervisor.reconcile(plan.operation_id).outcome == Outcome.OK
    assert supervisor.inspect()["pending_operations"] == []
    assert supervisor.store.read()["circuit"], "verification does not silently rearm automation"
    supervisor.configure(rearm=True)
    assert not supervisor.store.read()["circuit"]


@pytest.mark.parametrize("case,expected", [("live", True), ("reused", False), ("old-boot", False),
                                            ("missing", False), ("unreadable", None), ("unknown-schema", None)])
def test_lease_identity_does_not_confuse_old_boot_reused_pid_and_unknown(tmp_path, case, expected):
    boot = "12345678-1234-1234-1234-123456789012"
    (tmp_path / "sys/kernel/random").mkdir(parents=True)
    (tmp_path / "sys/kernel/random/boot_id").write_text(boot)
    process = tmp_path / "123"
    process.mkdir()
    (process / "stat").write_text("123 (test process) S " + "0 " * 18 + "77 0")
    owner = {"pid": 123, "start_ticks": 77, "boot_id": boot}
    if case == "reused": owner["start_ticks"] = 78
    if case == "old-boot": owner["boot_id"] = "22345678-1234-1234-1234-123456789012"
    if case == "missing": (process / "stat").unlink()
    if case == "unreadable": (process / "stat").write_text("incomplete")
    if case == "unknown-schema": owner["other"] = True
    assert action._alive(owner, proc_root=tmp_path) is expected


def test_automatic_bootstrap_waits_for_peers_then_registers_only_enabled_baseline(supervisor):
    supervisor.configure(enabled=True)
    supervisor.native.report["blockers"] = ["peer owns input"]
    assert supervisor.tick()["state"] == "waiting"
    assert supervisor.store.read()["baseline"] == {}
    supervisor.native.report["blockers"] = []
    assert supervisor.tick()["state"] == "observing"
    assert not supervisor.store.read()["baseline"], "broken first observation is not a healthy baseline"
    supervisor.native.report["devices"][0]["enabled"] = True
    assert supervisor.tick()["state"] == "observing"
    assert KEY in supervisor.store.read()["baseline"]
    supervisor.native.report["devices"][0]["enabled"] = False
    assert supervisor.tick()["outcome"] == "sucesso"
    assert len(supervisor.native.calls) == 1


def test_healthy_hotplug_enrollment_preserves_absent_device_baseline(supervisor):
    supervisor.configure(enabled=True)
    supervisor.native.report["devices"][0]["enabled"] = True
    supervisor.tick()
    supervisor.native.report["devices"][0].update(key="b" * 64, event="event9", name="New keyboard")
    supervisor.tick()
    assert set(supervisor.store.read()["baseline"]) == {KEY, "b" * 64}
    supervisor.native.report["devices"][0]["enabled"] = False
    assert supervisor.tick()["outcome"] == "sucesso"


def test_persistent_cooldown_and_budget_survive_new_supervisor_instance(supervisor):
    supervisor.native.report["devices"][0]["enabled"] = True
    supervisor.configure(enabled=True, capture=True)
    clock = [10000]
    supervisor.now = lambda: clock[0]
    for index in range(4):
        supervisor.native.report["devices"][0]["enabled"] = False
        result = supervisor.tick()
        assert result["outcome"] == ("sucesso" if index < 3 else "recusa")
        if index == 0:
            same = action.Supervisor(native=supervisor.native, store=supervisor.store,
                                     coordinator=supervisor.coordinator, now=lambda: clock[0])
            supervisor.native.report["devices"][0]["enabled"] = False
            assert same.tick()["outcome"] == "recusa"
        clock[0] += 61
    assert len(supervisor.native.calls) == 3


@pytest.mark.parametrize("body", ['{"schema":99}', '{broken', '{"schema":true}'])
def test_corrupt_unknown_and_boolean_schemas_do_not_enable_repairs(supervisor, body):
    supervisor.store.path.parent.mkdir(mode=0o700)
    supervisor.store.path.write_text(body)
    supervisor.store.path.chmod(0o600)
    value = supervisor.inspect()
    assert value["blockers"] and value["plans"] == []
    assert not value["policy"]["enabled"]


def test_stale_snapshot_no_backend_or_ambiguous_device_never_authorizes_plan():
    value = report()
    value["mono"] -= 30
    assert action.plans(value) == []
    value = report(); value["backend"] = "observe-only"
    assert action.plans(value) == []
    value = report(); value["devices"][0]["repairable"] = False
    assert action.plans(value) == []


def test_lease_holds_children_and_dead_repairer_remains_unknown(tmp_path, monkeypatch):
    folder = tmp_path / "leases"; folder.mkdir(mode=0o700)
    path = folder / "peer.json"
    value = {"schema": 1, "provider": "Other application", "resource": "input", "state": "using",
             "owner": {"role": "parent"}, "children": [{"role": "child"}]}
    action.save_object(path, value)
    monkeypatch.setattr(action, "_alive", lambda owner: owner["role"] == "child")
    assert action.lease_blockers(tmp_path)
    monkeypatch.setattr(action, "_alive", lambda owner: False)
    assert action.lease_blockers(tmp_path) == []
    value["state"] = "repairing"; action.save_object(path, value)
    assert "desconhecido" in action.lease_blockers(tmp_path)[0]
    value["state"] = "using"; action.save_object(path, value)
    monkeypatch.setattr(action, "_alive", lambda owner: None)
    assert action.lease_blockers(tmp_path)


def test_cooperating_market_app_acquires_and_releases_without_external_project(supervisor):
    value = action.publish_lease("test application", os.getpid(), "using", store=supervisor.store,
                                 coordinator=supervisor.coordinator)
    assert value["owner"]["boot_id"]
    assert supervisor.inspect()["blockers"]
    action.publish_lease("test application", os.getpid(), "released", store=supervisor.store,
                        coordinator=supervisor.coordinator)
    assert not supervisor.inspect()["blockers"]


def test_lease_preserves_live_child_when_parent_omits_it_and_reuses_provider_slot(supervisor):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        first = action.publish_lease("launcher", os.getpid(), "using", child_pids=[child.pid],
                                    store=supervisor.store, coordinator=supervisor.coordinator)
        with pytest.raises(ValueError, match="filhos"):
            action.publish_lease("launcher", os.getpid(), "released", store=supervisor.store,
                                  coordinator=supervisor.coordinator)
    finally:
        child.terminate(); child.wait(timeout=2)
    released = action.publish_lease("launcher", os.getpid(), "released", store=supervisor.store,
                                    coordinator=supervisor.coordinator)
    assert first["lease_id"] == released["lease_id"]
    assert len(list((supervisor.store.root / "leases").iterdir())) == 1


def test_dead_repair_lease_requires_explicit_verified_reconciliation(supervisor, monkeypatch):
    key = "d" * 32
    path = supervisor.store.root / "leases" / (key + ".json")
    action.save_object(path, {"schema": 1, "provider": "market app", "resource": "input",
                              "state": "repairing", "owner": {"old": True}, "children": []})
    monkeypatch.setattr(action, "_alive", lambda owner: False)
    with pytest.raises(ValueError):
        action.reconcile_lease(key, confirmed=True, supervisor=supervisor)
    supervisor.native.report["devices"][0]["enabled"] = True
    assert action.reconcile_lease(key, confirmed=True, supervisor=supervisor)["ok"]
    assert not action.lease_blockers(supervisor.store.root) and not supervisor.native.calls


@pytest.fixture
def host(tmp_path, monkeypatch, fake_home):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    proc, sysroot = tmp_path / "proc", tmp_path / "sys"
    (proc / "bus/input").mkdir(parents=True)
    (proc / "sys/kernel/random").mkdir(parents=True)
    (proc / "sys/kernel/random/boot_id").write_text("boot")
    (sysroot / "class/dmi/id").mkdir(parents=True)
    (sysroot / "class/dmi/id/product_name").write_text("Laptop")
    (proc / "bus/input/devices").write_text(
        'I: Bus=0003 Vendor=1234 Product=5678 Version=0001\nN: Name="USB Keyboard"\n'
        'P: Phys=usb-port/input0\nH: Handlers=kbd event3\nB: KEY=200100040000000\n')
    calls = []
    tools = {"qdbus6"}
    def run(argv, **kwargs):
        calls.append(argv)
        if "GetNameOwner" in argv[-2]:
            text = ":1.42\n"
        elif "GetConnectionUnixUser" in argv[-2]:
            text = str(os.getuid()) + "\n"
        elif argv[-1] == "devicesSysNames":
            text = "event3\n"
        elif argv[2].endswith("event3"):
            text = ('name: USB Keyboard\nsysName: event3\nenabled: true\nkeyboard: true\n'
                    'alphaNumericKeyboard: true\nisVirtual: false\nsupportsDisableEvents: true\n')
        elif argv[2] == "/VirtualKeyboard":
            text = "available: true\nmode: 1\n"
        elif "systemctl" in argv[0]:
            text = "active\n"
        else:
            text = ""
        return SimpleNamespace(returncode=0, stdout=text)
    native = NativeInput(runner=run, which=lambda name: "/fake/" + name if name in tools else None,
                         proc_root=proc, sys_root=sysroot)
    return native, tools, calls, fake_home


def test_host_without_phasezero_has_native_capabilities_and_no_phantom_dependency(host):
    native, tools, calls, home = host
    value = native.collect()
    assert value["backend"] == "kwin" and value["devices"][0]["repairable"]
    assert not value["blockers"] and not value["providers"]
    assert next(card for card in value["cards"] if card["key"] == "touch")["state"] == "not-observed"


def test_other_desktop_headless_and_missing_tools_keep_readonly_observations(host, monkeypatch):
    native, tools, calls, home = host
    tools.clear(); monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    value = native.collect()
    assert value["backend"] == "observe-only" and value["devices"]
    assert action.plans(value) == []
    (native.proc_root / "bus/input/devices").unlink()
    value = native.collect()
    assert value["errors"] and all(card["state"] == "unknown" for card in value["cards"][:5])


def test_registered_peer_is_optional_but_active_or_invalid_peer_blocks(host):
    native, tools, calls, home = host
    marker = home / ".config/phasezero/desktop-session.json"
    marker.parent.mkdir()
    marker.write_text(json.dumps({"schema_version": 1, "managed_by": "phasezero-input",
                                 "command": ["/missing/python", "/missing/backend"]}))
    tools.add("systemctl")
    assert "PhaseZero" in native.collect()["blockers"][0]
    marker.write_text('{"schema_version":999}')
    assert native.collect()["blockers"]
    marker.unlink()
    assert not native.collect()["blockers"]


def test_removed_phasezero_with_inactive_registration_allows_native_fallback(host):
    native, tools, calls, home = host
    marker = home / ".config/phasezero/desktop-session.json"; marker.parent.mkdir()
    marker.write_text(json.dumps({"schema_version": 1, "managed_by": "phasezero-input",
                                 "command": ["/removed/python", "/removed/phasezero"]}))
    tools.add("systemctl")
    original = native.runner
    native.runner = lambda argv, **kw: SimpleNamespace(returncode=0, stdout="inactive\n") if "systemctl" in argv[0] else original(argv, **kw)
    assert not native.collect()["blockers"]


@pytest.mark.parametrize("mapping,blocked", [
    ({"privileged": False, "devices": None, "mounts": []}, False),
    ({"privileged": True, "devices": [], "mounts": []}, True),
    ({"privileged": False, "devices": [{"PathOnHost": "/dev/input/event3"}], "mounts": []}, True),
    ({"privileged": False, "devices": [], "mounts": [{"Type": "bind", "Source": "/"}]}, True),
    ({"unknown": True}, True),
])
def test_container_device_exposure_and_unknown_schemas_block_only_when_required(host, mapping, blocked):
    native, tools, calls, home = host
    tools.add("docker")
    original = native.runner
    def run(argv, **kwargs):
        if "docker" in argv[0]:
            return SimpleNamespace(returncode=0, stdout="a" * 64 if argv[1] == "ps" else json.dumps(mapping))
        return original(argv, **kwargs)
    native.runner = run
    assert bool(native.collect()["blockers"]) == blocked
    assert not any("Env" in str(call) for call in calls)


def test_compositor_from_another_user_cannot_be_repaired(host):
    native, tools, calls, home = host
    original = native.runner
    def run(argv, **kwargs):
        if "GetConnectionUnixUser" in argv[-2]:
            return SimpleNamespace(returncode=0, stdout=str(os.getuid() + 1))
        return original(argv, **kwargs)
    native.runner = run
    value = native.collect()
    assert value["backend"] == "observe-only" and value["errors"]
    assert not any(device["repairable"] for device in value["devices"])


def test_cli_readonly_and_confirmed_policy_flow_use_same_supervisor(supervisor, monkeypatch, capsys):
    from folego import cli
    monkeypatch.setattr(action, "Supervisor", lambda: supervisor)
    assert cli.main(["accessibility", "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["backend"] == "kwin"
    assert cli.main(["accessibility", "enable", "--json"]) == 2
    capsys.readouterr()
    assert not supervisor.store.path.exists()
    assert cli.main(["accessibility", "enable", "--confirmar", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["enabled"] is True
    assert not supervisor.native.calls


def test_cli_repair_and_operation_query_share_stable_id(supervisor, monkeypatch, capsys):
    from folego import cli
    monkeypatch.setattr(action, "Supervisor", lambda: supervisor)
    plan = action.plans(supervisor.inspect())[0]
    assert cli.main(["accessibility", "repair", "--plan", json.dumps(plan.to_dict()), "--confirmar", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["operation_id"] == plan.operation_id
    monkeypatch.setattr("folego.orchestration.journal.Journal", lambda: supervisor.coordinator.journal)
    assert cli.main(["operation", plan.operation_id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["state"]["result"]["effects"]["enabled"] is True


def test_duplicate_physical_identity_cannot_be_repaired(host):
    native, _, _, _ = host
    path = native.proc_root / "bus/input/devices"
    body = path.read_text()
    devices = parse_devices(body + "\n" + body.replace("event3", "event4"))
    assert len(devices) == 2 and not any(device["stable"] for device in devices)


def test_touch_is_required_only_on_observed_deck_model(host):
    native, _, _, _ = host
    (native.sys_root / "class/dmi/id/product_name").write_text("Jupiter")
    assert next(card for card in native.collect()["cards"] if card["key"] == "touch")["state"] == "unavailable"


def test_native_collection_has_total_deadline_even_with_optional_tools(host):
    native, _, calls, _ = host
    ticks = iter((0, 9, 10, 11, 12))
    native.clock = lambda: next(ticks)
    value = native.collect()
    assert value["errors"] and not calls


def test_query_deadline_and_output_budget_terminate_only_disposable_children():
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_command([sys.executable, "-c", "import time; time.sleep(2)"], timeout=.05)
    with pytest.raises(subprocess.SubprocessError):
        bounded_command([sys.executable, "-c", "print('x'*300000)"], timeout=2)


def test_query_timeout_also_stops_own_descendant_after_leader_exits(tmp_path):
    pidfile = tmp_path / "child-pid"
    code = ("import subprocess,sys; from pathlib import Path; "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)']); "
            f"Path({str(pidfile)!r}).write_text(str(p.pid))")
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_command([sys.executable, "-c", code], timeout=.4)
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            return
        if state == "Z":
            return
        time.sleep(.01)
    pytest.fail("descendente da consulta descartável permaneceu ativo")


def test_user_unit_preserves_personal_unit_and_install_never_touches_other_units(fake_home, monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr("folego.actions.accessibility_service.shutil.which", lambda _: "/fake/systemctl")
    path = fake_home / ".config/systemd/user" / UNIT
    path.parent.mkdir(parents=True)
    path.write_text("personal unit")
    calls = []
    run = lambda argv, **kwargs: calls.append(argv) or SimpleNamespace(returncode=0, stdout=str(path))
    with pytest.raises(ValueError, match="pessoal"):
        install(confirmed=True, run=run)
    assert not calls and path.read_text() == "personal unit"
    path.unlink()
    assert install(confirmed=True, run=run)["ok"]
    assert calls == [["/fake/systemctl", "--user", "daemon-reload"],
                     ["/fake/systemctl", "--user", "show", UNIT, "--property=FragmentPath", "--value"],
                     ["/fake/systemctl", "--user", "enable", "--now", UNIT]]
    assert "PartOf=graphical-session.target" in path.read_text()


def test_headless_watch_runs_without_ui_or_peers_and_writes_observable_status(supervisor):
    result = watch(supervisor=supervisor, cycles=1)
    assert result == {"ok": True, "cycles": 1}
    value = action.read_object(supervisor.store.root / "watch-status.json")
    assert value["result"]["state"] == "paused" and not supervisor.native.calls
