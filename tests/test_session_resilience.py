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


def test_closed_temporaries_archive_without_payload_deletion_and_unknown_is_preserved(tmp_path, monkeypatch):
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
    second = jobtemp.prepare_job_environment({}, root=run.parent, mounts=(("/", "ext4"),))
    assert jobtemp._archive_completed(run.parent)["archived"] == 0
    assert Path(second["TMPDIR"]).exists()


def test_tuning_review_binds_content_and_stable_id_and_replays_without_effect(fake_home, monkeypatch):
    from folego.actions.tunings.engine import TuningEngine
    monkeypatch.setattr("folego.actions.tunings.engine.browser.edge_running", lambda: None)
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
