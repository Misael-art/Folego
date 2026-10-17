"""Disk hygiene M5 — quarantine: reclaim space reversibly, purge only on a second call."""
import json
import os

import pytest

from folego.actions.disk.quarantine import Quarantine
from folego.safely.audit import AuditLog


@pytest.fixture
def area(fake_home):
    """The user tree being reclaimed, isolated by the fake_home fixture."""
    src = fake_home / ".cache" / "oldproject"
    (src / "build").mkdir(parents=True)
    (src / "build" / "artifact.bin").write_bytes(b"z" * 4096)
    (src / "note.txt").write_text("oi")
    return src


def make_quarantine(fake_home, audit=None, stat_fn=os.stat):
    root = fake_home / ".local" / "share" / "folego" / "quarantine"
    return Quarantine(root, allowed_roots=[fake_home], audit=audit, stat_fn=stat_fn)


def test_move_in_frees_the_original_path_and_keeps_bytes(area, fake_home):
    q = make_quarantine(fake_home)

    entry = q.move_in(area)

    assert not area.exists()
    assert os.path.isdir(entry.stored)
    assert entry.bytes == 4096 + len("oi")
    assert q.entries()[entry.entry_id].state == "stored"


def test_restore_puts_everything_back(area, fake_home):
    q = make_quarantine(fake_home)
    entry = q.move_in(area)

    result = q.restore(entry.entry_id)

    assert result.ok is True
    assert (area / "build" / "artifact.bin").read_bytes() == b"z" * 4096
    assert (area / "note.txt").read_text() == "oi"
    assert q.entries()[entry.entry_id].state == "restored"


def test_manifest_survives_reload(area, fake_home):
    q = make_quarantine(fake_home)
    entry = q.move_in(area)

    reloaded = make_quarantine(fake_home)

    assert reloaded.entries()[entry.entry_id].original == str(area)
    assert reloaded.entries()[entry.entry_id].bytes == entry.bytes


def test_purge_is_explicit_and_idempotent(area, fake_home):
    q = make_quarantine(fake_home)
    entry = q.move_in(area)

    assert q.purge(entry.entry_id).ok is True
    assert not os.path.exists(entry.stored)
    second = q.purge(entry.entry_id)
    assert second.ok is False
    assert "purged" in second.reason


def test_restore_refuses_when_original_reappeared(area, fake_home):
    q = make_quarantine(fake_home)
    entry = q.move_in(area)
    area.mkdir(parents=True)
    (area / "novo.txt").write_text("dados novos")

    result = q.restore(entry.entry_id)

    assert result.ok is False
    assert "already exists" in result.reason
    assert (area / "novo.txt").read_text() == "dados novos"
    assert q.entries()[entry.entry_id].state == "stored"


def test_blacklisted_and_foreign_paths_are_refused(area, fake_home):
    q = make_quarantine(fake_home)

    for bad in ("/mnt/sdcard/.cache", "/home/other/.cache", "/etc/fonts"):
        with pytest.raises(PermissionError, match="refused"):
            q.move_in(bad)


def test_cross_device_move_is_refused(area, fake_home):
    real_stat = os.stat

    def other_device_stat(path, *args, **kwargs):
        st = real_stat(path, *args, **kwargs)
        if str(path) == str(area):

            class Shifted:
                st_dev = st.st_dev + 1
                st_mode = st.st_mode
                st_ino = st.st_ino
                st_size = st.st_size
                st_uid = st.st_uid

            return Shifted()
        return st

    q = make_quarantine(fake_home, stat_fn=other_device_stat)

    with pytest.raises(PermissionError, match="cross-device"):
        q.move_in(area)
    assert area.exists()


def test_symlink_is_refused(fake_home, tmp_path):
    victim = tmp_path / "real"
    victim.mkdir()
    (victim / "f.bin").write_bytes(b"x")
    (fake_home / ".cache").mkdir(parents=True, exist_ok=True)
    link = fake_home / ".cache" / "link"
    link.symlink_to(victim)

    q = make_quarantine(fake_home)
    with pytest.raises(PermissionError, match="refused"):
        q.move_in(link)
    assert victim.exists()


def test_every_move_is_audited(area, fake_home):
    audit = AuditLog(fake_home / ".local" / "state" / "folego" / "audit.jsonl")
    q = make_quarantine(fake_home, audit=audit)

    entry = q.move_in(area)
    q.restore(entry.entry_id)

    kinds = [(r["kind"], r["outcome"], r["action_id"]) for r in audit.tail(10)]
    assert ("disk.quarantine", "stored", entry.entry_id) in kinds
    assert ("disk.restore", "restored", entry.entry_id) in kinds


def test_reconcile_repairs_an_interrupted_move(area, fake_home):
    """Crash window: manifest says planned, the rename already happened."""
    q = make_quarantine(fake_home)
    entry = q.move_in(area)
    raw = json.loads(q.manifest_path.read_text())
    raw[0]["state"] = "planned"
    q.manifest_path.write_text(json.dumps(raw))

    repaired = q.reconcile()

    assert repaired == [entry.entry_id]
    assert q.entries()[entry.entry_id].state == "stored"


def test_reconcile_leaves_true_planned_entries_alone(area, fake_home):
    q = make_quarantine(fake_home)
    q.root.mkdir(parents=True, exist_ok=True)
    q.manifest_path.write_text(json.dumps([{
        "entry_id": "ghost-1", "original": str(area / "ghost"),
        "stored": str(q.root / "ghost-1"), "bytes": 0, "state": "planned",
        "moved_at": "", "action_id": "disk.quarantine"}]))

    assert q.reconcile() == []
    assert q.entries()["ghost-1"].state == "planned"


def test_move_in_refuses_inside_the_quarantine_root_itself(area, fake_home):
    q = make_quarantine(fake_home)
    entry = q.move_in(area)

    with pytest.raises(PermissionError, match="quarantine"):
        q.move_in(entry.stored)


def test_empty_dir_and_hidden_names_roundtrip(fake_home):
    src = fake_home / ".cache" / ".hidden.thing"
    src.mkdir(parents=True)
    q = make_quarantine(fake_home)

    entry = q.move_in(src)
    assert entry.bytes == 0
    assert q.restore(entry.entry_id).ok is True
    assert src.is_dir()


def test_manifest_is_owner_only(area, fake_home):
    q = make_quarantine(fake_home)
    q.move_in(area)

    assert (q.manifest_path.stat().st_mode & 0o077) == 0
