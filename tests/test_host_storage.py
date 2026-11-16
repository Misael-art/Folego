from pathlib import Path
from types import SimpleNamespace

from folego.actions.disk import usage
from folego.adapters.host_storage import observe_storage, read_mountinfo


def test_nvme_capacity_is_shared_and_trend_uses_the_previous_sample(tmp_path):
    mountinfo = tmp_path / "self/mountinfo"
    mountinfo.parent.mkdir()
    mountinfo.write_text(
        "36 25 0:28 /@ / rw - btrfs /dev/nvme0n1p2 rw\n"
        f"37 36 0:28 /@home {tmp_path} rw - btrfs /dev/nvme0n1p2 rw\n")
    (tmp_path / "class/block/nvme0n1p2").mkdir(parents=True)
    mounts = read_mountinfo(tmp_path)
    path = tmp_path / "history.json"
    free = 75

    def blocks(target):
        return SimpleNamespace(f_fsid=39 if target == str(tmp_path) else 51,
                               f_blocks=1000, f_bfree=free, f_bavail=free,
                               f_frsize=1024 ** 3, f_bsize=1024 ** 3)

    def observe(at, record=False):
        return observe_storage(mounts, sys_root=tmp_path, state_path=path,
                               now=at, record=record, statvfs=blocks, home=tmp_path)

    first = observe(10_000, record=True)
    assert len(first["volumes"]) == 1
    row = first["volumes"][0]
    assert row["nvme"] and row["level"] == "high"
    assert row["roles"] == ["Pasta pessoal", "Sistema"]
    assert row["trend"] is None
    saved = path.read_bytes()
    free = 45
    second = observe(13_600)
    row = second["volumes"][0]
    assert row["level"] == "critical"
    assert row["trend"] == {"elapsed_s": 3600, "available_delta_bytes": -30 * 1024 ** 3}
    assert path.read_bytes() == saved
    path.write_bytes(b'{"schema":99}')
    assert observe(14_200, record=True)["history_reason"]
    assert path.read_bytes() == b'{"schema":99}'


def test_unverified_mount_is_never_measured(tmp_path):
    mount = {"mount": "/", "source": "server:/path", "type": "nfs", "mount_id": "45"}

    def unexpected(_path):
        raise AssertionError("não consultar montagem remota")

    result = observe_storage([mount], sys_root=tmp_path, state_path=tmp_path / "state",
                             now=100, statvfs=unexpected, home=tmp_path, record=True)
    assert result["quality"] == "unknown"
    assert not result["volumes"]
    assert not (tmp_path / "state").exists()


def test_usage_reports_blocks_and_does_not_follow_a_selected_or_nested_link(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    fd = usage.os.open(home, usage._DIRECTORY)
    try:
        mount_id = usage._mount_id(fd)
    finally:
        usage.os.close(fd)
    monkeypatch.setattr(usage, "read_mountinfo", lambda _root: [
        {"mount": str(home), "source": "/dev/test", "type": "ext4", "mount_id": mount_id},
    ])
    subtree = home / "selected"
    subtree.mkdir()
    with (subtree / "sparse").open("wb") as stream:
        stream.write(b"data")
        stream.truncate(16 * 1024 ** 2)
    (subtree / "hardlink").hardlink_to(subtree / "sparse")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "private").write_bytes(b"private")
    (subtree / "excluded").symlink_to(tmp_path / "outside", target_is_directory=True)
    result = usage.inventory(subtree, home=home)
    assert result["quality"] == "ok"
    assert result["allocated_bytes"] == (subtree / "sparse").stat().st_blocks * 512
    assert len(result["items"]) == 1
    assert usage.inventory(subtree / "excluded", home=home)["quality"] == "unknown"
    assert usage.inventory(Path("/"), home=home)["quality"] == "unknown"
    partial = usage.inventory(subtree, home=home, max_entries=1)
    assert partial["quality"] == "partial"
    assert partial["scanned_entries"] == 1
