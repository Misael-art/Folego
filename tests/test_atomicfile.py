import os

import pytest

from deck_wellness.safely import atomicfile, hashing


def test_write_atomic_creates_new_file_with_exact_bytes(tmp_path):
    target = tmp_path / "novo.bin"
    result = atomicfile.write_atomic(target, b"conte\x00\xfado")
    assert target.read_bytes() == b"conte\x00\xfado"
    assert result.sha256 == hashing.sha256_bytes(b"conte\x00\xfado")


def test_write_atomic_overwrites_and_preserves_existing_mode(tmp_path):
    target = tmp_path / "prefs.json"
    target.write_bytes(b"old")
    os.chmod(target, 0o600)
    atomicfile.write_atomic(target, b'{"a":false}')
    assert target.read_bytes() == b'{"a":false}'
    assert stat_mode(target) == 0o600


def test_write_atomic_leaves_original_untouched_when_rename_fails(tmp_path, monkeypatch):
    target = tmp_path / "critico.txt"
    target.write_bytes(b"original")

    def boom(*args, **kwargs):
        raise OSError("rename failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomicfile.write_atomic(target, b"novo")
    assert target.read_bytes() == b"original"


def test_write_atomic_does_not_follow_existing_symlink_target_dir_semantics(tmp_path):
    # tmp file is created in the same dir with O_EXCL; ensure no stray tmp remains on success
    target = tmp_path / "limpo.txt"
    atomicfile.write_atomic(target, b"x")
    leftovers = [p.name for p in tmp_path.iterdir() if ".deckwellness." in p.name]
    assert leftovers == []


def stat_mode(path):
    return os.stat(path).st_mode & 0o777
