"""Disk hygiene M5 — tree measurement. Pure reader, no mutation."""
import os
import subprocess
from contextlib import nullcontext
from types import SimpleNamespace

from folego.actions.disk.measure import measure_tree


def _write(path, size: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_counts_regular_files_only(tmp_path):
    _write(tmp_path / "a" / "one.bin", 100)
    _write(tmp_path / "a" / "b" / "two.bin", 250)
    _write(tmp_path / "a" / "three.bin", 7)

    stat = measure_tree(tmp_path / "a")

    assert stat.bytes == 357
    assert stat.files == 3
    assert stat.errors == ()
    assert stat.truncated is False


def test_matches_du_apparent_sizes(tmp_path):
    """Independent cross-check: plan totals must agree with `du -ab`, the same
    command a human would run to validate the dry-run."""
    _write(tmp_path / "tree" / "x.bin", 4096)
    _write(tmp_path / "tree" / "sub" / "y.bin", 1000)
    _write(tmp_path / "tree" / "sub" / "z.bin", 23)

    ours = measure_tree(tmp_path / "tree")

    out = subprocess.run(
        ["du", "-ab", str(tmp_path / "tree")], capture_output=True, text=True, check=True
    ).stdout
    du_total = 0
    for line in out.splitlines():
        size_str, _, name = line.partition("\t")
        if name and os.path.isfile(name) and not os.path.islink(name):
            du_total += int(size_str)

    assert ours.bytes == du_total


def test_does_not_follow_symlinks(tmp_path):
    outside = tmp_path / "outside.bin"
    _write(outside, 5000)
    tree = tmp_path / "tree"
    _write(tree / "real.bin", 10)
    (tree / "link.bin").symlink_to(outside)

    stat = measure_tree(tree)

    assert stat.bytes == 10
    assert stat.files == 1


def test_permission_denied_is_recorded_not_raised(tmp_path):
    tree = tmp_path / "tree"
    _write(tree / "ok.bin", 11)
    locked = tree / "locked"
    _write(locked / "hidden.bin", 999)
    os.chmod(locked, 0o000)
    try:
        stat = measure_tree(tree)
    finally:
        os.chmod(locked, 0o755)

    assert stat.bytes == 11
    assert any("locked" in e for e in stat.errors)


def test_missing_root_degrades(tmp_path):
    stat = measure_tree(tmp_path / "nope")

    assert stat.bytes == 0
    assert stat.files == 0
    assert stat.errors


def test_tracks_newest_mtime(tmp_path):
    tree = tmp_path / "tree"
    _write(tree / "old.bin", 1)
    os.utime(tree / "old.bin", (1_600_000_000, 1_600_000_000))
    _write(tree / "new.bin", 1)

    stat = measure_tree(tree)

    assert stat.newest_ns == os.stat(tree / "new.bin").st_mtime_ns
    assert stat.newest_ns > 1_600_000_000 * 10**9


def test_deadline_stops_walk_and_marks_truncated(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    for i in range(20):
        _write(tree / f"d{i}" / "f.bin", 1)

    calls = []

    def clock():
        calls.append(1)
        return 0.0 if len(calls) <= 2 else 10_000.0

    stat = measure_tree(tree, deadline_s=0.001, clock=clock)

    assert stat.truncated is True
    assert stat.files < 20


class _FakeEntry:
    def __init__(self, name, *, is_dir, dev, size):
        self.name = name
        self._is_dir = is_dir
        self._dev = dev
        self._size = size

    @property
    def path(self):
        return self.name

    def is_dir(self, *, follow_symlinks=True):
        return self._is_dir

    def is_symlink(self):
        return False

    def stat(self, *, follow_symlinks=True):
        return SimpleNamespace(st_size=self._size, st_dev=self._dev,
                               st_mode=0o040755 if self._is_dir else 0o100644,
                               st_mtime_ns=1_700_000_000 * 10**9)


def test_cross_device_entries_are_skipped(tmp_path, monkeypatch):
    """A mount point inside the tree (e.g. /mnt/sdcard bind) must never be walked."""
    tree = tmp_path / "tree"
    _write(tree / "local.bin", 5)
    home_dev = os.stat(tree).st_dev

    def fake_scandir(path):
        if str(path) == str(tree):
            return nullcontext(iter([
                _FakeEntry("local.bin", is_dir=False, dev=home_dev, size=5),
                _FakeEntry("foreign", is_dir=True, dev=home_dev + 1, size=0),
            ]))
        raise AssertionError(f"walked into cross-device dir: {path}")

    stat = measure_tree(tree, scandir_fn=fake_scandir)

    assert stat.bytes == 5
    assert any("foreign" in e for e in stat.errors)
