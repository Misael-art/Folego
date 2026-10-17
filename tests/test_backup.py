import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from folego.safely import backup, hashing


@pytest.fixture
def store(fake_home):
    return backup.BackupStore(fake_home / ".local" / "share" / "folego" / "backups")


@pytest.fixture
def edge_files(tmp_path):
    profile = tmp_path / "edge-profile" / "Default"
    profile.mkdir(parents=True)
    prefs = profile / "Preferences"
    prefs.write_bytes(b'{"browser":{"x":1}}')
    state = tmp_path / "edge-profile" / "Local State"
    state.write_bytes(b'{"browser":{"startup_boost_enabled":true}}')
    return prefs, state


def test_create_stores_byte_exact_copy_and_manifest(store, edge_files, tmp_path):
    prefs, state = edge_files
    bid = store.create(
        "edge_startup_boost",
        [
            backup.BackupEntry(target=prefs, sha_after_expected="deadbeef"),
            backup_entry(state),
        ],
    )
    bdir = store.path_of(bid)
    manifest = json.loads((bdir / "manifest.json").read_text())
    assert manifest["action_id"] == "edge_startup_boost"
    assert (bdir / "files" / "000.bin").read_bytes() == prefs.read_bytes()
    assert (bdir / "files" / "001.bin").read_bytes() == state.read_bytes()
    e0 = manifest["entries"][0]
    assert e0["sha_before"] == hashing.sha256_file(prefs)
    assert e0["sha_after_expected"] == "deadbeef"


def test_restore_returns_exact_original_bytes(store, edge_files):
    prefs, _ = edge_files
    bid = store.create("t", [backup_entry(prefs)])
    prefs.write_bytes(b'mutated')
    results = store.restore(bid)
    assert prefs.read_bytes() == b'{"browser":{"x":1}}'
    assert results[0].ok and results[0].sha == hashing.sha256_file(prefs)


def test_restore_refuses_corrupted_payload(store, edge_files):
    prefs, _ = edge_files
    original = prefs.read_bytes()
    bid = store.create("t", [backup_entry(prefs)])
    payload = store.path_of(bid) / "files" / "000.bin"
    payload.write_bytes(b"tampered")
    results = store.restore(bid)
    assert not results[0].ok
    assert prefs.read_bytes() == original  # untouched on integrity failure


def test_latest_picks_newest_backup_for_action(store, edge_files, monkeypatch):
    prefs, _ = edge_files
    b1 = store.create("dup", [backup_entry(prefs)])
    monkeypatch.setattr(backup.time, "time", lambda: 1_800_000_000.0)
    b2 = store.create("dup", [backup_entry(prefs)])
    assert store.latest_backup_id("dup") == b2
    assert store.latest_backup_id("inexistente") is None
    assert b1 != b2


def test_create_requires_existing_target(store, tmp_path):
    with pytest.raises(FileNotFoundError):
        store.create("t", [backup.BackupEntry(target=tmp_path / "nao-existe", sha_after_expected=None)])


def backup_entry(path, sha_after=None):
    return backup.BackupEntry(target=path, sha_after_expected=sha_after)


@given(payload=st.binary(max_size=2048), mutation=st.binary(max_size=2048))
def test_roundtrip_property(payload, mutation, tmp_path_factory):
    root = tmp_path_factory.mktemp("prop")
    backups = root / "backups"
    backups.mkdir()
    store = backup.BackupStore(backups)
    target = root / "file.json"
    target.write_bytes(payload)
    bid = store.create("prop", [backup_entry(target)])
    target.write_bytes(mutation)
    store.restore(bid)
    assert target.read_bytes() == payload
