"""A rescue plan must fail closed before it could ever touch a live volume."""
import os
from types import SimpleNamespace

from folego.adapters.ntfs_recovery import assess_ntfs_recovery


def _runner(*, destination_source="/dev/sdb1", source_mounts=()):
    rows = [
        {"path": "/dev/mmcblk0", "pkname": None, "type": "disk"},
        {"path": "/dev/mmcblk0p1", "pkname": "mmcblk0", "type": "part",
         "fstype": "ntfs", "uuid": "58D14C064972BE55", "size": 500_000_000,
         "mountpoints": list(source_mounts)},
        {"path": "/dev/sdb", "pkname": None, "type": "disk"},
        {"path": "/dev/sdb1", "pkname": "sdb", "type": "part"},
    ]

    def run(argv):
        if argv[0] == "lsblk":
            return {"blockdevices": rows}
        assert argv[0] == "findmnt"
        return {"filesystems": [{"source": destination_source,
                                 "fstype": "ext4", "target": argv[3]}]}

    return run


def test_recovery_preflight_blocks_live_card_without_independent_destination(tmp_path):
    report = assess_ntfs_recovery(
        "/dev/mmcblk0p1", str(tmp_path),
        run=_runner(destination_source="/dev/mmcblk0p1",
                    source_mounts=("/mnt/sdcard",)),
        access=lambda _path, mode: mode == os.W_OK,
        statvfs=lambda *_: SimpleNamespace(f_bavail=10**9, f_frsize=4096),
        which=lambda *_: None)
    assert report["can_image"] is False
    assert any("montada" in item for item in report["blockers"])
    assert any("mesmo dispositivo" in item for item in report["blockers"])
    assert any("autenticação" in item for item in report["blockers"])
    assert any("ddrescue" in item for item in report["blockers"])


def test_recovery_preflight_needs_space_and_accepts_separate_empty_volume(tmp_path):
    args = dict(run=_runner(), access=lambda *_: True,
                which=lambda *_: "/usr/bin/ddrescue")
    small = assess_ntfs_recovery(
        "/dev/mmcblk0p1", str(tmp_path),
        statvfs=lambda *_: SimpleNamespace(f_bavail=1, f_frsize=4096), **args)
    assert not small["can_image"]
    assert any("espaço insuficiente" in item for item in small["blockers"])
    large = assess_ntfs_recovery(
        "/dev/mmcblk0p1", str(tmp_path),
        statvfs=lambda *_: SimpleNamespace(f_bavail=10**9, f_frsize=4096), **args)
    assert large["can_image"] is True
    assert large["blockers"] == []
