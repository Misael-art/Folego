import json
import os
from pathlib import Path
import time
import uuid

import pytest

from folego import startup
from folego.actions import accessibility as access
from folego.orchestration import Coordinator
from folego.orchestration.history import PendingReader, READ_BUDGET
from folego.orchestration.journal import Journal
from folego.orchestration.models import ActionPlan, ActionResult, Outcome, ResourceIdentity
from folego.orchestration import review
from folego.safely import jobtemp
from test_cli_tmpfs import fake_tmp


def test_startup_default_and_opt_out_persist_without_enabling_effects(fake_home, monkeypatch):
    monkeypatch.setattr(startup.shortcuts, "launcher_executable", lambda: Path("/bin/true"))
    assert startup.preference()["enabled"] is True
    assert startup.configure(manage_service=False)["enabled"] is True
    path = startup.paths.autostart_path()
    assert "Hidden=false" in path.read_text()
    startup.configure(False, confirmed=True, manage_service=False)
    assert not startup.configure(manage_service=False)["enabled"]
    assert "Hidden=true" in path.read_text()
    assert access.Store().read()["enabled"] is False


def test_personal_and_symlink_autostart_are_preserved(fake_home, monkeypatch):
    path = startup.paths.autostart_path()
    path.parent.mkdir(parents=True)
    path.write_text("[Desktop Entry]\nExec=personal\n")
    with pytest.raises(ValueError, match="pessoal"):
        startup.configure(True, confirmed=True, manage_service=False)
    assert "personal" in path.read_text()
    path.unlink()
    path.symlink_to(fake_home / "missing")
    with pytest.raises(ValueError): startup.configure(True, confirmed=True, manage_service=False)


def test_concurrent_startup_choices_leave_unit_at_the_latest_preference(fake_home, monkeypatch):
    import subprocess
    import threading

    monkeypatch.setattr(startup.shortcuts, "launcher_executable", lambda: Path("/bin/true"))
    unit = startup.paths.xdg_config_home() / "systemd/user" / startup.UNIT
    unit.parent.mkdir(parents=True)
    unit.write_text(startup.MARKER + "\n[Unit]\n")
    current = {"enabled": False}
    installing, release, disabled = threading.Event(), threading.Event(), threading.Event()

    def install(*, confirmed):
        assert confirmed
        installing.set()
        assert release.wait(3)
        current["enabled"] = True

    def service_status():
        return {"path": str(unit), "enabled": current["enabled"],
                "state": "active" if current["enabled"] else "inactive"}

    def command(argv, *, timeout):
        assert argv[-1] == startup.UNIT and "disable" in argv and "--now" in argv
        current["enabled"] = False
        disabled.set()
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(startup, "install", install)
    monkeypatch.setattr(startup, "service_status", service_status)
    monkeypatch.setattr(startup, "bounded_command", command)
    monkeypatch.setattr(startup.shutil, "which", lambda name: "/usr/bin/systemctl")
    results = []
    first = threading.Thread(target=lambda: results.append(startup.configure(True, confirmed=True)))
    second = threading.Thread(target=lambda: results.append(startup.configure(False, confirmed=True)))
    first.start()
    assert installing.wait(2)
    second.start()
    # Before the fix, the disable could finish while the old enable was paused.
    disabled.wait(.3)
    release.set()
    first.join(3); second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert len(results) == 2 and all(result["ok"] for result in results)
    assert startup.preference()["enabled"] is False
    assert "Hidden=true" in startup.paths.autostart_path().read_text()
    assert current["enabled"] is False


def test_startup_unit_timeout_keeps_choice_and_reports_unknown(fake_home, monkeypatch):
    import subprocess

    monkeypatch.setattr(startup.shortcuts, "launcher_executable", lambda: Path("/bin/true"))

    def timeout(*, confirmed):
        raise subprocess.TimeoutExpired(["systemctl", "--user", "enable"], 8)

    monkeypatch.setattr(startup, "install", timeout)
    result = startup.configure(True, confirmed=True)
    assert result["outcome"] == "desconhecido" and not result["ok"]
    assert result["errors"]
    assert startup.preference()["enabled"] is True
    assert "Hidden=false" in startup.paths.autostart_path().read_text()


def test_more_than_32_released_leases_do_not_block_and_closed_receipts_survive(tmp_path, monkeypatch):
    owner = {"pid": os.getpid(), "start_ticks": int(Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]),
             "boot_id": access.read_boot_id()}
    for index in range(40):
        provider = f"fixture-{index}"
        key = uuid.uuid5(uuid.NAMESPACE_URL, "folego-input:" + provider).hex
        access.save_object(tmp_path / "leases" / (key + ".json"),
            {"schema":1,"provider":provider,"resource":"input","state":"released","owner":owner,"children":[]})
    assert access.lease_blockers(tmp_path) == []
    assert access.archive_released_leases(tmp_path) == 32
    assert len(list((tmp_path / "leases-closed").iterdir())) == 32
    assert access.lease_blockers(tmp_path) == []


def test_pending_index_is_bounded_reuses_validated_state_and_detects_rewrite(tmp_path):
    journal = Journal(tmp_path / "journal")
    plan = ActionPlan("accessibility.enable-input", ResourceIdentity.entry("fixture"))
    journal.append_intent(plan)
    journal.append_result(ActionResult(plan.action, Outcome.UNKNOWN, plan.operation_id, target_key="fixture"))
    reader = PendingReader(journal, clock=lambda: 0)
    assert reader.ids() == [plan.operation_id]
    before = reader.bytes_read
    assert reader.ids() == [plan.operation_id] and reader.bytes_read == before
    journal.path.write_text(journal.path.read_text().replace('"schema": 1', '"schema": 99', 1))
    with pytest.raises(ValueError): reader.ids()
    assert reader.bytes_read - before <= READ_BUDGET


def test_bounded_pending_index_preserves_scopes_and_clears_them_with_the_receipt(tmp_path):
    from folego.actions.accessibility import unresolved
    journal = Journal(tmp_path / 'scoped-journal')
    plan = ActionPlan('accessibility.activate', ResourceIdentity.entry('touch'),
                      {'capabilities': ['touch'], 'peer': {'registered': True}})
    journal.append_intent(plan)
    reader = PendingReader(journal, clock=lambda: 0)
    assert reader.ids() == [plan.operation_id]
    assert 'keyboard' in reader.pending_scopes[plan.operation_id]
    assert 'microphone' not in reader.pending_scopes[plan.operation_id]
    assert unresolved(journal, capabilities=['microphone']) == []
    assert unresolved(journal, capabilities=['keyboard']) == [plan.operation_id]
    journal.append_result(ActionResult(plan.action, Outcome.OK, plan.operation_id, target_key='touch'))
    assert not reader.ids() and not reader.pending_scopes


def test_closed_temporaries_archive_without_payload_deletion_and_unknown_is_preserved(tmp_path, monkeypatch, capsys):
    env = jobtemp.prepare_job_environment({}, root=tmp_path / "jobs", mounts=(("/", "ext4"),))
    run = Path(env["TMPDIR"]).parent
    payload = run / "general/useful.txt"
    payload.write_text("preserve me")
    manifest = json.loads((run / "run.json").read_text())
    manifest.update(state="complete", child={"pid":1234567,"start_ticks":10,"boot_id":access.read_boot_id()},session=1234567)
    access.save_object(run / "run.json", manifest)
    monkeypatch.setattr(jobtemp, "_consumers", lambda: (set(), set(), set()))
    result = jobtemp._archive_completed(run.parent)
    assert result["archived"] == 1
    assert not run.exists()
    assert (run.parent / ".retained" / run.name / "general/useful.txt").read_text() == "preserve me"
    inventory = jobtemp.retention_status(run.parent)
    assert inventory["retained_count"] == 1
    assert inventory["retained_runs"] == [{"name": run.name, "state": "complete"}]
    restored = jobtemp.recover_retained(run.parent, run.name, mounts=(("/", "ext4"),))
    assert restored["state"] == "retained"
    assert (Path(restored["path"]) / "general/useful.txt").read_text() == "preserve me"
    assert jobtemp.recover_retained(run.parent, run.name, mounts=(("/", "ext4"),)) == restored
    from folego import cli
    monkeypatch.setattr(jobtemp, "read_mounts_checked", lambda: ((("/", "ext4"),), None))
    assert cli.main(["jobs", "recover", run.name, "--root", str(run.parent), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["path"] == restored["path"]
    assert cli.main(["jobs", "status", "--root", str(run.parent), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["retained_count"] == 1
    second = jobtemp.prepare_job_environment({}, root=run.parent, mounts=(("/", "ext4"),))
    assert jobtemp._archive_completed(run.parent)["archived"] == 0
    assert Path(second["TMPDIR"]).exists()


def test_retention_reports_unreadable_consumers_as_refusal_without_moving(tmp_path, monkeypatch, capsys):
    from folego import cli
    env = jobtemp.prepare_job_environment({}, root=tmp_path / "jobs", mounts=(("/", "ext4"),))
    run = Path(env["TMPDIR"]).parent
    manifest = json.loads((run / "run.json").read_text())
    manifest.update(state="complete", child={"pid":1234567,"start_ticks":10,
                                             "boot_id":access.read_boot_id()}, session=1234567)
    access.save_object(run / "run.json", manifest)
    monkeypatch.setattr(jobtemp, "read_mounts_checked", lambda: ((("/", "ext4"),), None))
    def unavailable():
        raise OSError("consumidor inacessível")
    monkeypatch.setattr(jobtemp, "_consumers", unavailable)
    assert cli.main(["jobs", "retain", "--root", str(run.parent), "--confirmar", "--json"]) != 0
    reply = json.loads(capsys.readouterr().out)
    assert reply["outcome"] == "recusa" and reply["blocked"] is True
    assert run.exists() and not (run.parent / ".retained" / run.name).exists()


def test_tuning_review_binds_content_and_stable_id_and_replays_without_effect(fake_home, monkeypatch):
    from folego.actions.tunings.engine import TuningEngine
    # Constructor defaults bind at import. Inject the dependency explicitly;
    # this disposable-file test must never inspect a real browser process.
    monkeypatch.setattr("folego.actions.tunings.engine.TuningEngine",
                        lambda *args, **kwargs: TuningEngine(*args, edge_running=lambda: None, **kwargs))
    path = fake_home / ".config/microsoft-edge/Local State"
    path.parent.mkdir(parents=True)
    path.write_text('{"startup_boost":{"enabled":true}}')
    bundle = review.prepare(["tune", "apply", "edge.startup_boost"])
    assert json.loads(path.read_text())["startup_boost"]["enabled"] is True
    with pytest.raises(ValueError): review.execute(bundle)
    result = review.execute(bundle, confirmed=True)
    assert result.outcome == Outcome.OK
    assert result.operation_id == bundle["plan"]["operation_id"]
    assert review.execute(bundle, confirmed=True) == result
    assert json.loads(path.read_text())["startup_boost"]["enabled"] is False


@pytest.mark.parametrize("outcome", [Outcome.OK, Outcome.UNKNOWN])
def test_performance_review_uses_one_id_and_reconciles_without_retry(fake_home, monkeypatch, capsys, outcome):
    from folego import cli
    from folego.orchestration.bridge import perform
    effects = []
    target = ResourceIdentity("group", "app-fixture.service", {
        "boot_id": "fixture", "rule": "steam-idle", "members": [{"pid": 123, "start_ticks": 5}]})
    params = {"rule": "steam-idle", "channel": "tray", "trigger": "manual"}
    def invoke(command):
        assert command[:2] == ["performance", "close"]
        return perform(coordinator=Coordinator(), action="performance.close", target=target,
                       params=params, act=lambda: effects.append(1) or True,
                       verdict=lambda _result, key: ActionResult("performance.close", outcome, "",
                                                                  target_key=key, reason="fixture"))
    monkeypatch.setattr(review, "_invoke", invoke)
    bundle = review.prepare(["performance", "close", "steam-idle", "--unit", target.key, "--json"])
    key = bundle["plan"]["operation_id"]
    assert effects == [] and bundle["evidence"]["summary"] == [{"key": target.key, "source": target.key}]
    first = review.execute(bundle, confirmed=True)
    assert first.operation_id == key and first.outcome is outcome and effects == [1]
    second = review.execute(bundle, confirmed=True)
    assert second.operation_id == key and effects == [1]
    consulted = review.reconcile(key)
    assert consulted.operation_id == key and consulted.outcome is outcome and effects == [1]
    if outcome is Outcome.UNKNOWN:
        with pytest.raises(ValueError, match="pendente"):
            review.prepare(["performance", "close", "steam-idle", "--unit", target.key, "--json"])
        assert effects == [1]
    assert cli.main(["review", "reconcile", key, "--json"]) == (0 if outcome is Outcome.OK else cli.EXIT_UNKNOWN)
    assert json.loads(capsys.readouterr().out)["operation_id"] == key


def test_tuning_changed_after_review_refuses_before_effect(fake_home):
    path = fake_home / ".config/microsoft-edge/Local State"
    path.parent.mkdir(parents=True)
    path.write_text('{"startup_boost":{"enabled":true}}')
    bundle = review.prepare(["tune", "apply", "edge.startup_boost"])
    path.write_text('{"startup_boost":{"enabled":true},"other":1}')
    result = review.execute(bundle, confirmed=True)
    assert result.outcome == Outcome.REFUSED
    assert json.loads(path.read_text())["startup_boost"]["enabled"] is True


def test_review_survives_restart_and_cancelled_review_never_executes(fake_home):
    path = fake_home / ".config/microsoft-edge/Local State"
    path.parent.mkdir(parents=True)
    path.write_text('{"startup_boost":{"enabled":true}}')
    bundle = review.prepare(["tune", "apply", "edge.startup_boost"])
    key = bundle["plan"]["operation_id"]
    assert any(row["operation_id"] == key for row in review.pending())
    with pytest.raises(ValueError, match="pendente"):
        review.prepare(["tune", "apply", "edge.startup_boost"])
    review.cancel(key, confirmed=True)
    assert review.pending() == []
    assert review.execute(bundle, confirmed=True).outcome == Outcome.CANCELLED
    assert json.loads(path.read_text())["startup_boost"]["enabled"] is True


def test_reconcile_known_journal_result_closes_started_review_once(fake_home):
    plan = ActionPlan("tune.apply", ResourceIdentity.entry("fixture"))
    bundle = {"schema": 1, "plan": plan.to_dict(),
              "command": ["tune", "apply", "fixture"],
              "evidence": {"proof": {}}, "state": "started"}
    review._save(bundle)
    journal = Journal()
    result = ActionResult(plan.action, Outcome.OK, plan.operation_id,
                          target_key=plan.target.key, reason="efeito já verificado")
    journal.append_intent(plan)
    journal.append_result(result)
    active = review._path(plan.operation_id)
    closed = active.parent.parent / "reviews-closed" / active.name
    assert review.reconcile(plan.operation_id) == result
    assert not active.exists() and closed.exists()
    before = closed.read_bytes()
    assert review.reconcile(plan.operation_id) == result
    assert review.execute(bundle, confirmed=True) == result
    # Crash between linking the closed receipt and removing its active copy.
    active.write_bytes(before)
    assert review.reconcile(plan.operation_id) == result
    assert closed.read_bytes() == before and not active.exists()
    assert review.pending() == []


def test_reconcile_preserves_conflicting_closed_receipt(fake_home):
    from folego.actions.accessibility import save_object
    plan = ActionPlan("tune.apply", ResourceIdentity.entry("fixture"))
    bundle = {"schema": 1, "plan": plan.to_dict(),
              "command": ["tune", "apply", "fixture"],
              "evidence": {"proof": {}}, "state": "started"}
    review._save(bundle)
    result = ActionResult(plan.action, Outcome.OK, plan.operation_id, target_key=plan.target.key)
    journal = Journal()
    journal.append_intent(plan)
    journal.append_result(result)
    active = review._path(plan.operation_id)
    closed = active.parent.parent / "reviews-closed" / active.name
    save_object(closed, {**bundle, "state": "closed", "result": {**result.to_dict(), "reason": "conflito"}})
    before_active, before_closed = active.read_bytes(), closed.read_bytes()
    with pytest.raises(ValueError, match="recibo encerrado"):
        review.reconcile(plan.operation_id)
    assert active.read_bytes() == before_active
    assert closed.read_bytes() == before_closed


@pytest.mark.parametrize("verb", ["restore", "purge"])
def test_disk_review_replays_same_operation_and_requires_irreversible_confirmation(fake_home, verb):
    from folego.actions.disk.quarantine import Quarantine
    source = fake_home / ".cache/demo"
    source.mkdir(parents=True)
    (source / "data.txt").write_text("disposable payload")
    book = Quarantine()
    entry = book.move_in(source, action_id="fixture")
    bundle = review.prepare(["disk", verb, entry.entry_id])
    if verb == "purge":
        with pytest.raises(ValueError, match="irreversível"):
            review.execute(bundle, confirmed=True)
    result = review.execute(bundle, confirmed=True, irreversible=verb == "purge")
    assert result.outcome == Outcome.OK
    assert review.execute(bundle, confirmed=True, irreversible=verb == "purge") == result
    assert source.exists() == (verb == "restore")


def test_suspend_time_invalidates_native_observation_and_unknown_clock_never_authorizes(monkeypatch):
    from folego.core import accessibility as core
    now = [100.0]
    monkeypatch.setattr(core, "observation_clock", lambda: now[0])
    report = {"schema":1,"mono":100.0,"clock":"boottime","boot_id":"boot"}
    assert access.fresh(report)
    now[0] += 3600
    assert not access.fresh(report)
    report.update(mono=now[0], clock="future-clock")
    assert not access.fresh(report)


def test_lease_run_registers_child_before_allowing_app_to_start(fake_home, monkeypatch):
    import sys
    from folego.actions import input_lease
    marker = fake_home / "app-ran"
    provider = "owned-fixture"
    key = uuid.uuid5(uuid.NAMESPACE_URL, "folego-input:" + provider).hex
    receipt = access.directory() / "leases" / (key + ".json")
    code = ("import os,json; from pathlib import Path; "
            f"r=json.loads(Path({str(receipt)!r}).read_text()); "
            "assert r['children'][0]['pid']==os.getpid(); "
            f"Path({str(marker)!r}).write_text('registered before effect')")
    monkeypatch.setattr(input_lease, "_members", lambda marker, session: [])
    assert input_lease.run(provider, [sys.executable, "-c", code]) == 0
    assert marker.read_text() == "registered before effect"
    assert json.loads(receipt.read_text())["state"] == "released"


def test_dead_gated_launcher_cannot_silently_release_consumers(tmp_path, monkeypatch):
    access.save_object(tmp_path / "leases/demo.json", {"schema":1,"provider":"fixture",
        "resource":"input","state":"using","owner":{},"children":[],"completion_required":True})
    monkeypatch.setattr(access, "_alive", lambda _: False)
    assert access.lease_blockers(tmp_path)


def test_released_flag_with_unknown_owner_is_not_proof_of_release(tmp_path):
    access.save_object(tmp_path / "leases/demo.json", {"schema":1,"provider":"fixture",
        "resource":"input","state":"released","owner":{},"children":[]})
    assert access.lease_blockers(tmp_path)


def test_transition_ring_observes_suspend_gap_reconnect_and_bounded_history(tmp_path):
    store = access.Store(tmp_path)
    report = {"boot_id":"boot","service_owner":":1.2","mono":100,"clock":"boottime",
              "backend":"kwin","cards":[{"key":"keyboard","state":"observed"}],
              "devices":[{"key":"fixture","enabled":True}],"blockers":[]}
    access.record_transition(store, report)
    report["mono"] += 3600
    report["service_owner"] = ":1.8"
    event = access.record_transition(store, report)
    assert "observation-gap" in event["kinds"] and "compositor" in event["kinds"]
    assert event["physical_verified"] is False
    for index in range(40):
        report["devices"][0]["enabled"] = index % 2 == 0
        report["mono"] += 10
        access.record_transition(store, report)
    assert len(access.transition_history(store)["events"]) == 32


def test_copied_manifest_cannot_certify_another_directory(tmp_path):
    import shutil
    env = jobtemp.prepare_job_environment({}, root=tmp_path / "jobs", mounts=(("/", "ext4"),))
    source = Path(env["TMPDIR"]).parent
    target = tmp_path / "imported" / source.name
    shutil.copytree(source, target)
    with pytest.raises(OSError, match="identidade"):
        jobtemp._manifest(target / "run.json")


@pytest.mark.parametrize("verb", ["restore", "expire"])
def test_tmpfs_review_preserves_same_id_and_exact_victims(fake_home, fake_tmp, tmp_path, monkeypatch, verb):
    from test_cli_tmpfs import tmpfs_env, backdate
    from folego import cli
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    monkeypatch.setattr(cli, "_tmpfs_coordinator", lambda: Coordinator())
    source = root / "qoder-cli-1000"
    release = review.prepare(["tmpfs", "release", str(source)])
    released = review.execute(release, confirmed=True)
    assert released.outcome == Outcome.OK and not source.exists()
    entry_id = released.effects["entry_id"]
    if verb == "expire": backdate(tmp_path, 30)
    command = ["tmpfs", verb, entry_id] if verb == "restore" else ["tmpfs", verb]
    bundle = review.prepare(command)
    assert bundle["evidence"]["summary"][0]["key"] == entry_id
    result = review.execute(bundle, confirmed=True, irreversible=verb == "expire")
    assert result.outcome == Outcome.OK, result
    assert result.operation_id == bundle["plan"]["operation_id"]
    assert review.execute(bundle, confirmed=True, irreversible=verb == "expire") == result
    assert source.exists() == (verb == "restore")
