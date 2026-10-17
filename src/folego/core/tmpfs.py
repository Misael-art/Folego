"""Capacidade dos tmpfs que viram RAM: /tmp, /run/user/1000 e /dev/shm.

Ler isto não custa nada: /proc/mounts e um statvfs por volume, sem walk de árvore
e sem varrer fd — por isso cabe no poller de 2 s. É watch-list nominal: o host
monta tmpfs em /run, /run/credentials/* e outros lugares que nenhum agente
escreve. Nada aqui estatiza algo sob /mnt ou /run/media.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from .. import paths

WATCHED = ("/tmp", "/run/user/1000", "/dev/shm")
_ESCAPES = {"\\040": " ", "\\011": "\t", "\\012": "\n", "\\134": "\\"}


@dataclass(frozen=True)
class TmpfsVolume:
    path: str
    fs_type: str
    total_bytes: int
    used_bytes: int
    avail_bytes: int

    @property
    def used_frac(self) -> float:
        return self.used_bytes / self.total_bytes if self.total_bytes else 0.0

    def to_dict(self) -> dict:
        return {"path": self.path, "fs_type": self.fs_type,
                "total_bytes": self.total_bytes, "used_bytes": self.used_bytes,
                "avail_bytes": self.avail_bytes,
                "used_pct": round(self.used_frac * 100, 1)}


def _unescape(field: str) -> str:
    for needle, char in _ESCAPES.items():
        field = field.replace(needle, char)
    return field


def read_mounts(proc_root: str | None = None) -> tuple:
    """(mount_point, fs_type) por linha; () se o /proc não responder."""
    try:
        raw = (Path(proc_root or paths.proc_root()) / "mounts").read_text()
    except OSError:
        return ()
    out = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            out.append((_unescape(parts[1]), parts[2]))
    return tuple(out)


def watched_volumes(*, proc_root: str | None = None, statvfs_fn=os.statvfs,
                    watched=WATCHED) -> tuple:
    result = []
    for mount, fs_type in read_mounts(proc_root):
        if fs_type != "tmpfs" or mount not in watched:
            continue
        try:
            vfs = statvfs_fn(mount)
        except OSError:
            continue
        frsize = vfs.f_frsize or vfs.f_bsize
        total = vfs.f_blocks * frsize
        used = (vfs.f_blocks - vfs.f_bfree) * frsize
        result.append(TmpfsVolume(mount, fs_type, total, used, vfs.f_bavail * frsize))
    return tuple(result)
