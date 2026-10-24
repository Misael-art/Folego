import errno
import os

import pytest

from folego.core.runtime import discover_runtime
from folego.core.tmpfs import watched_volumes
from folego.actions.tmpfs.holders import holder_index
from folego.safely.jobtemp import prepare_job_environment
from folego.safely.jobtemp import prevention_status


def test_runtime_uses_uid_not_1000_and_rejects_other_owner(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    uid = os.getuid()
    assert discover_runtime(env={"XDG_RUNTIME_DIR": str(runtime)}, uid=uid).valid
    assert not discover_runtime(env={"XDG_RUNTIME_DIR": str(runtime)}, uid=uid + 1).valid
    assert discover_runtime(env={}, uid=12345).path == "/run/user/12345"


def test_runtime_symlinks_and_public_permissions_are_rejected(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o755)
    runtime.chmod(0o755)  # The fixture must be public even with a private umask.
    assert not discover_runtime(env={"XDG_RUNTIME_DIR": str(runtime)}).valid
    runtime.chmod(0o700)
    link = tmp_path / "link"
    link.symlink_to(runtime, target_is_directory=True)
    assert not discover_runtime(env={"XDG_RUNTIME_DIR": str(link)}).valid


def test_custom_runtime_is_collected_and_stat_failure_is_visible(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    def denied(path):
        raise PermissionError(errno.EACCES, "denied")
    volumes = watched_volumes(mounts=((str(runtime), "tmpfs"),), statvfs_fn=denied)
    assert len(volumes) == 1 and volumes[0].is_runtime
    assert volumes[0].quality == "error"
    assert "denied" in volumes[0].to_dict()["error"]


def test_denied_individual_fd_readlink_is_not_complete(tmp_path):
    fd = tmp_path / "123/fd"
    fd.mkdir(parents=True)
    (fd / "1").touch()
    def denied(path):
        raise PermissionError(errno.EACCES, "opaque fd")
    result = holder_index(proc_root=str(tmp_path), readlink_fn=denied)
    assert result.state == "partial" and result.errors


def test_cwd_and_mmap_are_references_without_open_descriptors(tmp_path):
    proc = tmp_path / "proc/123"
    (proc / "fd").mkdir(parents=True)
    (proc / "cwd").symlink_to("/fixtures/pytest-1")
    (proc / "maps").write_text("1000-2000 r--p 00000000 08:01 1 /fixtures/pytest-2/data\n")
    result = holder_index(proc_root=str(proc.parent), prefixes=("/fixtures",),
                          include_process_refs=True)
    assert result.state == "complete"
    assert result.pids_holding("/fixtures/pytest-1") == frozenset({123})
    assert result.pids_holding("/fixtures/pytest-2") == frozenset({123})


def test_child_temporaries_override_old_runtime_and_preserve_session(tmp_path):
    root = tmp_path / "jobs"
    env = {"TMPDIR": "/run/user/1000/codex-desktop/tmp", "XDG_RUNTIME_DIR": "/run/user/1000"}
    mounts = (("/", "ext4"), ("/run/user/1000", "tmpfs"))
    a = prepare_job_environment(env, root=root, mounts=mounts)
    b = prepare_job_environment(env, root=root, mounts=mounts)
    assert a["TMPDIR"] != b["TMPDIR"]
    assert a["PYTEST_DEBUG_TEMPROOT"] != a["TMPDIR"]
    assert a["TMPDIR"].startswith(str(root))
    assert a["XDG_RUNTIME_DIR"] == env["XDG_RUNTIME_DIR"]
    assert env["TMPDIR"].startswith("/run/")


def test_temporary_destination_in_ram_is_refused_before_creation(tmp_path):
    root = tmp_path / "jobs"
    with pytest.raises(OSError, match="RAM"):
        prepare_job_environment({}, root=root, mounts=(("/", "tmpfs"),))
    assert not root.exists()


def test_job_retention_limit_preserves_previous_run_and_blocks_new_job(tmp_path):
    root = tmp_path / "jobs"
    first = prepare_job_environment({}, root=root, mounts=(("/", "ext4"),), max_runs=1)
    with pytest.raises(OSError, match="limite de execuções"):
        prepare_job_environment({}, root=root, mounts=(("/", "ext4"),), max_runs=1)
    assert os.path.isdir(first["TMPDIR"])


def test_existing_phasezero_root_is_used_without_profile_changes(tmp_path):
    phasezero = tmp_path / "phasezero/agent-tmp"
    phasezero.mkdir(parents=True)
    env = prepare_job_environment({"TMPDIR": str(phasezero)}, mounts=(("/", "btrfs"),))
    assert env["TMPDIR"].startswith(str(phasezero / "folego-jobs"))


def test_phasezero_config_is_respected_even_with_old_inherited_environment(tmp_path):
    config = tmp_path / ".config/environment.d/70-phasezero-agent-tmp.conf"
    config.parent.mkdir(parents=True)
    original = 'TMPDIR=${HOME}/.cache/phasezero/agent-tmp\n'
    config.write_text(original)
    runtime = str(tmp_path / "runtime")
    inherited = {"HOME": str(tmp_path), "XDG_RUNTIME_DIR": runtime,
                 "TMPDIR": runtime + "/codex-desktop/tmp"}
    status = prevention_status(inherited)
    assert status["inherited_runtime_tmpdir"] is True
    child = prepare_job_environment(inherited, mounts=(("/", "ext4"), (runtime, "tmpfs")))
    assert child["TMPDIR"].startswith(str(tmp_path / ".cache/phasezero/agent-tmp/folego-jobs"))
    assert config.read_text() == original
    assert inherited["TMPDIR"].startswith(runtime)
