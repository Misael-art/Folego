"""F8 single instance: one flock, visible holder, no silent second UI."""
import os
import stat

import pytest

from folego.core.instance import AlreadyRunning, InstanceLock


def test_a_second_lock_in_the_same_process_is_refused(tmp_path):
    path = tmp_path / "gui.lock"
    first = InstanceLock(path)
    first.acquire()
    try:
        with pytest.raises(AlreadyRunning) as caught:
            InstanceLock(path).acquire()
        assert caught.value.holder_pid == os.getpid()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.read_text().strip() == str(os.getpid())
    finally:
        first.release()


def test_release_allows_a_new_instance_and_keeps_the_file(tmp_path):
    path = tmp_path / "gui.lock"
    with InstanceLock(path):
        pass
    assert path.exists(), "não removemos o arquivo: evita corrida de unlink"

    second = InstanceLock(path)
    second.acquire()
    second.release()
    assert not second.locked


def test_release_is_idempotent(tmp_path):
    lock = InstanceLock(tmp_path / "gui.lock")
    lock.acquire()
    lock.release()
    lock.release()
    assert not lock.locked
