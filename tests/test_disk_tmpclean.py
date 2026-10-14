"""Disk hygiene M5 — /tmp expiry. The Deck's tmpfs is RAM-backed and fills up,
raising ENOSPC for bash, git and this app even when the disk has room. Contents
there are declared disposable, but only our own files, only old ones."""
import os
import time

import pytest

from deck_wellness.actions.disk import tmpclean
from deck_wellness.safely.audit import AuditLog

DAY = 86_400


@pytest.fixture
def tmp_dir(tmp_path, fake_home):
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    return scratch


def _make(root, name, days_ago, *, is_dir=False, content=b"x"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if is_dir:
        (path / "inner.bin").mkdir(parents=True)
        (path / "inner.bin" / "f.bin").write_bytes(content * 10)
    else:
        path.write_bytes(content * 10)
    ts = time.time() - days_ago * DAY
    for dirpath, dirnames, filenames in os.walk(path):
        for entry in filenames + dirnames:
            os.utime(os.path.join(dirpath, entry), (ts, ts))
        os.utime(dirpath, (ts, ts))
    os.utime(path, (ts, ts))
    return path


def test_plan_only_lists_expired_owned_entries(tmp_dir):
    old = _make(tmp_dir, "pytest-of-misael", 4, is_dir=True)
    fresh = _make(tmp_dir, "sessao-atual", 1, is_dir=True)

    plan = tmpclean.plan_tmp(tmp_dir, min_age_days=3)

    assert [i.path for i in plan.items] == [str(old)]
    assert plan.kept == (str(fresh),)
    assert plan.total_bytes == old.joinpath("inner.bin", "f.bin").stat().st_size


def test_plan_skips_files_owned_by_someone_else(tmp_dir, monkeypatch):
    foreign = _make(tmp_dir, "de-outro", 10)

    class Other:
        st_uid = os.stat(tmp_dir).st_uid + 1
        st_mode = foreign.stat().st_mode
        st_size = foreign.stat().st_size
        st_mtime_ns = foreign.stat().st_mtime_ns
        st_dev = foreign.stat().st_dev
        st_ino = foreign.stat().st_ino

    monkeypatch.setattr(tmpclean, "_lstat", lambda p: Other())

    plan = tmpclean.plan_tmp(tmp_dir, min_age_days=3)

    assert plan.items == ()


def test_plan_never_follows_symlinks(tmp_dir):
    victim = _make(tmp_dir / "real", "precioso", 0)
    link = tmp_dir / "link-velho"
    link.symlink_to(victim / "precioso")
    stale = time.time() - 10 * DAY
    os.utime(link, (stale, stale), follow_symlinks=False)

    plan = tmpclean.plan_tmp(tmp_dir, min_age_days=3)

    assert plan.items == ()
    assert victim.exists()


def test_missing_directory_degrades_to_empty_plan(tmp_path):
    plan = tmpclean.plan_tmp(tmp_path / "nao-existe", min_age_days=3)

    assert plan.items == ()
    assert plan.total_bytes == 0


def test_expire_deletes_only_planned_entries_and_is_audited(tmp_dir, fake_home):
    old = _make(tmp_dir, "velho", 5, is_dir=True)
    fresh = _make(tmp_dir, "novo", 1, is_dir=True)
    expected = old.joinpath("inner.bin", "f.bin").stat().st_size
    audit = AuditLog(fake_home / "audit.jsonl")

    result = tmpclean.expire_tmp(tmp_dir, min_age_days=3, audit=audit)

    assert result.removed == (str(old),)
    assert result.freed_bytes == expected
    assert not old.exists()
    assert fresh.exists()
    record = audit.tail(1)[0]
    assert record["kind"] == "disk.tmp-expire"
    assert record["outcome"] == "expired"
    assert record["risk"] == "irreversible"
    assert record["targets"] == [str(old)]


def test_expire_without_audit_still_works(tmp_dir):
    old = _make(tmp_dir, "velho2", 9)

    result = tmpclean.expire_tmp(tmp_dir, min_age_days=3)

    assert result.removed == (str(old),)
    assert not old.exists()


def test_expire_survives_an_entry_that_vanishes_or_refuses(tmp_dir):
    """A racing remover (another session cleaning /tmp) or a busy dir must not
    abort the pass: the failure is recorded, the rest is still freed."""
    first = _make(tmp_dir, "corrida", 5)
    second = _make(tmp_dir, "travado", 6)
    attempts = []

    def flaky_remove(path, *, is_dir):
        attempts.append(str(path))
        if str(path) == str(first):
            raise FileNotFoundError(f"{path} já se foi")

    result = tmpclean.expire_tmp(tmp_dir, min_age_days=3, remove_fn=flaky_remove)

    assert result.removed == (str(second),)
    assert result.errors and "corrida" in result.errors[0]
    assert len(attempts) == 2
    assert first.exists() and second.exists()
