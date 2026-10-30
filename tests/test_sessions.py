"""F3.5: opt-in session registry, UUIDs, reboot/PID-reuse identity, artifacts."""
import json
import os

import pytest

from folego.core.sessions import (ACTIVE, DISCONNECTED, ENDED, HEARTBEAT_LOST,
                                  SessionError, SessionPolicy, SessionRegistry,
                                  read_cgroup)
from fixtures_proc import pid_dir, set_proc_fields


PID = 4242


@pytest.fixture
def proc_root(tmp_path):
    root = tmp_path / "proc"
    (root / "sys" / "kernel" / "random").mkdir(parents=True)
    (root / "sys" / "kernel" / "random" / "boot_id").write_text("boot-a\n")
    pid_dir(root, PID, comm="builder", uid=os.getuid(), starttime=777)
    return root


@pytest.fixture
def clock():
    now = [1_000.0]

    def tick(seconds=0.0):
        now[0] += seconds
        return now[0]

    return now, tick


def registry(tmp_path, proc_root, clock, **kw):
    return SessionRegistry(tmp_path / "sessions.json", proc_root=proc_root,
                           clock=clock[1], **kw)


def test_registry_is_opt_in_and_creates_no_file_just_by_reading(tmp_path,
                                                                proc_root,
                                                                clock):
    store = registry(tmp_path, proc_root, clock)

    assert store.list() == ()
    assert store.snapshot() == ()
    assert not store.path.exists(), "reading cannot opt the user in"
    assert not store._lock_path.exists(), "reading must not create a lock sidecar"


def test_register_uses_a_uuid_and_survives_a_reload(tmp_path, proc_root, clock):
    store = registry(tmp_path, proc_root, clock)
    item = store.register(PID, project="Folego", label="build",
                          keep_active=True)

    assert item.session_id.count("-") == 4
    assert item.state == ACTIVE and item.keep_active
    assert item.starttime == 777 and item.boot_id == "boot-a"

    again = registry(tmp_path, proc_root, clock).list()
    assert len(again) == 1
    assert again[0].session_id == item.session_id
    assert again[0].project == "Folego"


def test_register_is_idempotent_for_the_same_pid_identity(tmp_path, proc_root,
                                                          clock):
    store = registry(tmp_path, proc_root, clock)
    first = store.register(PID)
    second = store.register(PID, project="p", keep_active=True)

    assert second.session_id == first.session_id
    assert second.project == "p" and second.keep_active
    assert len(store.list()) == 1


def test_heartbeat_disconnect_and_heartbeat_lost_are_distinct(tmp_path,
                                                              proc_root,
                                                              clock):
    store = registry(tmp_path, proc_root, clock,
                     policy=SessionPolicy(heartbeat_ttl_s=10.0))
    item = store.register(PID)
    assert item.state == ACTIVE

    disconnected = store.disconnect(item.session_id)
    assert disconnected.state == DISCONNECTED
    clock[0][0] += 100.0
    assert store.list()[0].state == DISCONNECTED, (
        "an explicit disconnect is not silently relabelled as heartbeat loss")

    revived = store.heartbeat(item.session_id)
    assert revived.state == ACTIVE
    clock[0][0] += 100.0
    lost = store.list()[0]
    assert lost.state == HEARTBEAT_LOST
    assert lost.keep_active is False


def test_keep_active_survives_heartbeat_loss_but_not_explicit_end(tmp_path,
                                                                  proc_root,
                                                                  clock):
    store = registry(tmp_path, proc_root, clock,
                     policy=SessionPolicy(heartbeat_ttl_s=1.0))
    item = store.register(PID, keep_active=True)
    clock[0][0] += 10.0
    assert store.keep_active_reason(PID, 777), "losing the heartbeat is not consent to kill"
    assert store.list()[0].state == HEARTBEAT_LOST

    store.end(item.session_id)
    assert store.keep_active_reason(PID, 777) is None


def test_a_changed_boot_id_ends_the_old_session_and_a_new_one_starts_fresh(
        tmp_path, proc_root, clock):
    store = registry(tmp_path, proc_root, clock)
    old = store.register(PID, keep_active=True)
    (proc_root / "sys" / "kernel" / "random" / "boot_id").write_text("boot-b\n")

    ended = store.list()[0]
    assert ended.state == ENDED
    assert "boot" in (ended.ended_reason or "")
    assert store.keep_active_reason(PID, 777) is None

    fresh = store.register(PID, keep_active=True)
    assert fresh.session_id != old.session_id
    assert fresh.boot_id == "boot-b"


def test_a_zombie_is_not_a_live_session(tmp_path, proc_root, clock):
    set_proc_fields(proc_root, PID, state="Z")

    with pytest.raises(SessionError):
        registry(tmp_path, proc_root, clock).register(PID)


def test_a_session_whose_process_became_a_zombie_is_ended(tmp_path, proc_root,
                                                          clock):
    store = registry(tmp_path, proc_root, clock)
    store.register(PID, keep_active=True)
    set_proc_fields(proc_root, PID, state="Z")

    assert store.list()[0].state == ENDED
    assert store.keep_active_reason(PID, 777) is None


def test_pid_reuse_ends_the_old_session_instead_of_inheriting_it(tmp_path,
                                                                 proc_root,
                                                                 clock):
    store = registry(tmp_path, proc_root, clock)
    old = store.register(PID, keep_active=True)
    set_proc_fields(proc_root, PID, starttime=999)

    ended = store.list()[0]
    assert ended.state == ENDED
    assert "reutilizado" in (ended.ended_reason or "")
    assert store.keep_active_reason(PID, 999) is None
    assert store.find_pid(PID, 999) is None

    fresh = store.register(PID, keep_active=True)
    assert fresh.session_id != old.session_id
    assert fresh.starttime == 999


def test_artifacts_have_a_lifetime_and_are_never_deleted_here(tmp_path,
                                                              proc_root,
                                                              clock):
    store = registry(tmp_path, proc_root, clock,
                     policy=SessionPolicy(artifact_ttl_days=1.0))
    item = store.register(PID)
    art = store.add_artifact(item.session_id, "/tmp/cache/build.tar",
                             size_bytes=123, kind="archive")
    assert art.expires_at == 1_000.0 + 86_400

    clock[0][0] += 86_401
    expired = store.expired_artifacts()
    assert [a.path for a in expired] == ["/tmp/cache/build.tar"]
    assert (tmp_path / "cache").exists() is False, "listing never touches the path"


def test_artifact_requires_an_absolute_path(tmp_path, proc_root, clock):
    store = registry(tmp_path, proc_root, clock)
    item = store.register(PID)
    with pytest.raises(SessionError):
        store.add_artifact(item.session_id, "relative/path")


def test_a_corrupt_registry_fails_closed(tmp_path, proc_root, clock):
    store = registry(tmp_path, proc_root, clock)
    store.register(PID)
    store.path.write_text("{not json")

    with pytest.raises(SessionError):
        store.list()
    reason = store.keep_active_reason(PID, 777)
    assert reason and "ilegível" in reason, "unknown must not mean unprotected"


def test_unknown_schema_version_is_refused(tmp_path, proc_root, clock):
    store = registry(tmp_path, proc_root, clock)
    store.register(PID)
    raw = json.loads(store.path.read_text())
    raw["version"] = 999
    store.path.write_text(json.dumps(raw))

    with pytest.raises(SessionError):
        store.snapshot()


def test_cgroup_is_stored_only_when_readable_and_in_the_user_slice(tmp_path,
                                                                   proc_root,
                                                                   clock):
    cgroup = proc_root / str(PID) / "cgroup"
    cgroup.write_text("0::/user.slice/user-1000.slice/session-2.scope\n")
    assert read_cgroup(PID, proc_root).endswith("session-2.scope")

    item = registry(tmp_path, proc_root, clock).register(PID)
    assert item.cgroup_verified and "user.slice" in (item.cgroup or "")

    cgroup.write_text("0::/system.slice/sshd.service\n")
    assert read_cgroup(PID, proc_root) is None
