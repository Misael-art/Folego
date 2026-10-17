"""Watch-list tmpfs: os três volumes que viram ENOSPC na RAM deste Deck.

O host monta tmpfs em muito mais lugares do que os que importam (/run,
/run/credentials/*, …), então isto é lista nominal, não "todo tmpfs".
"""
from collections import namedtuple

import pytest

from folego.core import tmpfs

GIB = 1024 ** 3
Statvfs = namedtuple("Statvfs", "f_frsize f_bsize f_blocks f_bfree f_bavail")

MOUNTS = """proc /proc proc rw,nosuid 0 0
tmpfs /tmp tmpfs rw,noatime,inode64 0 0
tmpfs /run/user/1000 tmpfs rw,nosuid,nodev,size=1517624k,mode=700 0 0
tmpfs /dev/shm tmpfs rw,nosuid,nodev,usrquota 0 0
tmpfs /run tmpfs rw,nosuid,nodev,size=761916k 0 0
tmpfs /run/credentials/systemd-networkd.service tmpfs ro,nosuid,nodev,noexec 0 0
/dev/nvme0n1p2 / ext4 rw,relatime 0 0
"""


def vfs(total_gib: float, used_gib: float) -> Statvfs:
    frsize = 4096
    blocks = int(total_gib * GIB) // frsize
    free = int((total_gib - used_gib) * GIB) // frsize
    return Statvfs(f_frsize=frsize, f_bsize=frsize, f_blocks=blocks,
                   f_bfree=free, f_bavail=free)


@pytest.fixture
def fake_mounts(fake_proc):
    (fake_proc / "mounts").write_text(MOUNTS)
    return fake_proc


def by_path(**stats):
    def statvfs_fn(path):
        return stats[str(path)]
    return statvfs_fn


def test_only_the_watch_list_tmpfs_are_reported(fake_mounts):
    got = tmpfs.watched_volumes(
        proc_root=str(fake_mounts),
        statvfs_fn=by_path(**{"/tmp": vfs(8, 2), "/run/user/1000": vfs(2, 0),
                              "/dev/shm": vfs(8, 1)}))
    assert [v.path for v in got] == ["/tmp", "/run/user/1000", "/dev/shm"]


def test_used_is_total_minus_free_and_avail_is_what_we_can_write(fake_mounts):
    got = tmpfs.watched_volumes(
        proc_root=str(fake_mounts),
        statvfs_fn=by_path(**{"/tmp": vfs(8, 2), "/run/user/1000": vfs(2, 0),
                              "/dev/shm": vfs(8, 1)}))
    assert (got[0].total_bytes, got[0].used_bytes, got[0].avail_bytes) == (
        8 * GIB, 2 * GIB, 6 * GIB)
    assert got[0].used_frac == pytest.approx(0.25)


def test_a_watched_path_that_is_not_tmpfs_is_not_measured(fake_proc):
    (fake_proc / "mounts").write_text("/dev/nvme0n1p2 /tmp ext4 rw 0 0\n")

    def never(path):
        raise AssertionError(f"statvfs chamado em {path}: o volume não é tmpfs")

    assert tmpfs.watched_volumes(proc_root=str(fake_proc), statvfs_fn=never) == ()


def test_a_volume_that_cannot_be_statvfs_is_dropped_not_invented(fake_mounts):
    def statvfs_fn(path):
        if str(path) == "/dev/shm":
            raise OSError("não montado")
        return vfs(8, 2)

    got = tmpfs.watched_volumes(proc_root=str(fake_mounts), statvfs_fn=statvfs_fn)
    assert [v.path for v in got] == ["/tmp", "/run/user/1000"]


def test_zero_sized_volume_does_not_divide_by_zero(fake_proc):
    (fake_proc / "mounts").write_text("tmpfs /tmp tmpfs rw 0 0\n")
    got = tmpfs.watched_volumes(proc_root=str(fake_proc), statvfs_fn=lambda p: vfs(0, 0))
    assert got[0].used_frac == 0.0


def test_to_dict_carries_the_rounded_used_pct(fake_mounts):
    """/tmp a 14,2857 % vira 14,3 %: é isto que a aba e o `--json` mostram."""
    got = tmpfs.watched_volumes(proc_root=str(fake_mounts),
                                statvfs_fn=by_path(**{"/tmp": vfs(7, 1),
                                                      "/run/user/1000": vfs(2, 1),
                                                      "/dev/shm": vfs(8, 0)}))
    assert got[0].to_dict()["used_pct"] == 14.3
    assert got[1].to_dict()["used_pct"] == 50.0


def test_missing_mounts_file_is_silence_not_an_exception(fake_proc):
    assert tmpfs.read_mounts(str(fake_proc)) == ()
    assert tmpfs.watched_volumes(proc_root=str(fake_proc),
                                 statvfs_fn=lambda p: vfs(8, 2)) == ()


def test_mount_points_unescape_the_kernel_octal_space(fake_proc):
    (fake_proc / "mounts").write_text("tmpfs /tmp/com\\040espaco tmpfs rw 0 0\n")
    assert ("/tmp/com espaco", "tmpfs") in tmpfs.read_mounts(str(fake_proc))


def test_the_document_portal_is_not_a_watched_volume(fake_proc):
    """/run/user/1000/doc é fuse.portal: fica de fora, e um statvfs nele nunca é chamado."""
    (fake_proc / "mounts").write_text("tmpfs /run/user/1000 tmpfs rw 0 0\n"
                                       "fuse.portal /run/user/1000/doc fuse.portal rw 0 0\n")

    def statvfs_fn(path):
        assert str(path) == "/run/user/1000"
        return vfs(2, 0)

    assert [v.path for v in tmpfs.watched_volumes(proc_root=str(fake_proc),
                                                  statvfs_fn=statvfs_fn)] == ["/run/user/1000"]
