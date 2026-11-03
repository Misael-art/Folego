import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from folego import cli
from folego.actions.tmpfs import runtime_size as action
from folego.core import runtime_size as sizes
from folego.orchestration import Coordinator
from folego.orchestration.journal import Journal
from folego.orchestration.models import Outcome, ResourceIdentity

MIB = sizes.MIB


@pytest.fixture
def runtime(tmp_path, monkeypatch, fake_home):
    volume = SimpleNamespace(path=f"/run/user/{os.getuid()}", quality="ok",
                             total_bytes=512 * MIB, used_frac=.5)
    target = ResourceIdentity("volume", volume.path, {"dev": 1, "ino": 2, "boot_id": "boot"})
    monkeypatch.setattr(action, "identity", lambda value: target)
    monkeypatch.setattr(sizes, "mem_total_bytes", lambda: 8 * 1024**3)
    configuration = {"size": 512 * MIB}
    monkeypatch.setattr(sizes, "configured_size", lambda: configuration["size"])
    coordinator = Coordinator(journal=Journal(tmp_path / "journal"), lock_path=tmp_path / "lock")
    return volume, configuration, coordinator


def test_resize_intent_precedes_effect_and_replaying_id_does_not_resize_again(runtime):
    volume, config, coordinator = runtime
    plan = action.plan_for(volume, 1024 * MIB)
    calls = []
    def run(argv, **kwargs):
        assert coordinator.journal.state_of(plan.operation_id).result is None
        calls.append(argv)
        volume.total_bytes = config["size"] = 1024 * MIB
        return SimpleNamespace(returncode=0, stdout="configured\n")
    for _ in range(2):
        result = action.apply(plan, coordinator=coordinator, volume_fn=lambda: volume,
                              run=run, receipt_fn=lambda _: (0, 1, 1, 1024))
        assert result.outcome == Outcome.OK and result.operation_id == plan.operation_id
    assert len(calls) == 1
    assert [row.kind for row in coordinator.journal.records()] == ["intent", "result"]


def test_remount_failure_is_partial_and_preserves_observed_configuration(runtime):
    volume, config, coordinator = runtime
    plan = action.plan_for(volume, 1024 * MIB)
    def run(argv, **kwargs):
        config["size"] = 1024 * MIB
        return SimpleNamespace(returncode=32, stdout="configured\n")
    result = action.apply(plan, coordinator=coordinator, volume_fn=lambda: volume,
                          run=run, receipt_fn=lambda _: (32, 1, 0, 1024))
    assert result.outcome == Outcome.PARTIAL
    assert result.effects["configured_bytes"] == 1024 * MIB
    assert result.effects["after_bytes"] == 512 * MIB
    assert coordinator.journal.state_of(plan.operation_id).result.outcome == Outcome.PARTIAL


def test_missing_receipt_after_configuration_is_unknown_even_for_exit_126(runtime):
    volume, config, coordinator = runtime
    plan = action.plan_for(volume, 1024 * MIB)
    def missing(_):
        raise FileNotFoundError("receipt could not be persisted")
    result = action.apply(plan, coordinator=coordinator, volume_fn=lambda: volume,
        run=lambda *a, **k: SimpleNamespace(returncode=126, stdout="configured\n"), receipt_fn=missing)
    assert result.outcome == Outcome.UNKNOWN


def test_privileged_shell_preserves_previous_file_and_writes_failure_receipt(tmp_path):
    bindir, configdir, runtime = (tmp_path / name for name in ("bin", "config", "runtime"))
    for folder in (bindir, configdir, runtime):
        folder.mkdir()
    for name, body in (("findmnt", "printf 'tmpfs\\n'"), ("mount", "exit 32")):
        tool = bindir / name
        tool.write_text("#!/bin/sh\n" + body + "\n")
        tool.chmod(0o700)
    dropin = configdir / "runtime.conf"
    dropin.write_text("previous configuration\n")
    op = "a" * 32
    command = sizes.apply_command(1024 * MIB, operation_id=op)
    result = subprocess.run(["/bin/sh", "-c", command[3], "assessment", str(configdir),
        sizes.dropin_text(1024 * MIB), str(dropin), "1024", str(runtime), op,
        "", "0", str(os.getuid())], env={**os.environ, "PATH": f"{bindir}:/usr/bin:/bin"})
    assert result.returncode == 32
    assert Path(f"{dropin}.before-{op}").read_text() == "previous configuration\n"
    assert Path(f"{dropin}.result-{op}").read_text().split() == [op, "32", "1", "0", "1024"]
    assert "RuntimeDirectorySize=1024M" in dropin.read_text()


def test_unknown_result_blocks_new_operation_until_explicit_verified_reconciliation(runtime):
    volume, config, coordinator = runtime
    plan = action.plan_for(volume, 1024 * MIB)
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired("pkexec", 175)
    result = action.apply(plan, coordinator=coordinator, volume_fn=lambda: volume, run=run)
    assert result.outcome == Outcome.UNKNOWN
    another = action.plan_for(volume, 1536 * MIB)
    result = action.apply(another, coordinator=coordinator, volume_fn=lambda: volume, run=run)
    assert result.outcome == Outcome.REFUSED and len(calls) == 1
    def missing(_):
        raise FileNotFoundError("no completed privileged receipt")
    assert action.reconcile(plan.operation_id, coordinator=coordinator,
                            volume_fn=lambda: volume, receipt_fn=missing).outcome == Outcome.UNKNOWN
    volume.total_bytes = config["size"] = 1024 * MIB
    result = action.reconcile(plan.operation_id, coordinator=coordinator,
                               volume_fn=lambda: volume, receipt_fn=lambda _: (0, 1, 1, 1024))
    assert result.outcome == Outcome.OK
    assert action.pending(coordinator.journal, volume.path) == []


@pytest.mark.parametrize("change", ["size", "cap"])
def test_changed_runtime_or_invalid_size_never_reaches_pkexec(runtime, change):
    volume, config, coordinator = runtime
    plan = action.plan_for(volume, 1024 * MIB if change == "size" else 7 * 1024 * MIB)
    if change == "size":
        volume.total_bytes = 768 * MIB
    def forbidden(*args, **kwargs):
        pytest.fail("must refuse before privileged execution")
    result = action.apply(plan, coordinator=coordinator, volume_fn=lambda: volume, run=forbidden)
    assert result.outcome == Outcome.REFUSED


def test_cli_options_carry_exact_reviewed_plan_and_pending_ids(runtime, monkeypatch, capsys):
    volume, config, coordinator = runtime
    monkeypatch.setattr(cli, "_tmpfs_runtime_volume", lambda: volume)
    monkeypatch.setattr(cli, "_tmpfs_coordinator", lambda: coordinator)
    plan = action.plan_for(volume, 1024 * MIB)
    coordinator.journal.append_intent(plan)
    assert cli.main(["tmpfs", "runtime-size", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pending_operation_ids"] == [plan.operation_id]
    assert payload["options"][1]["plan"]["params"]["size_bytes"] == 1024 * MIB


def test_cli_emits_operation_id_and_partial_exit(runtime, monkeypatch, capsys):
    volume, config, coordinator = runtime
    monkeypatch.setattr(cli, "_tmpfs_runtime_volume", lambda: volume)
    monkeypatch.setattr(cli, "_tmpfs_coordinator", lambda: coordinator)
    plan = action.plan_for(volume, 1024 * MIB)
    from folego.orchestration.models import ActionResult
    monkeypatch.setattr(action, "apply", lambda selected, **kw: ActionResult(
        action.ACTION, Outcome.PARTIAL, selected.operation_id, target_key=volume.path,
        reason="configuration written, remount failed"))
    assert cli.main(["tmpfs", "runtime-size", "--reviewed-plan", json.dumps(plan.to_dict()),
                     "--confirmar", "--json"]) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["operation_id"] == plan.operation_id and result["outcome"] == "parcial"
