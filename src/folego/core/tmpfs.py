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
from .runtime import discover_runtime

WATCHED = ("/tmp", f"/run/user/{os.getuid()}", "/dev/shm")
_ESCAPES = {"\\040": " ", "\\011": "\t", "\\012": "\n", "\\134": "\\"}


@dataclass(frozen=True)
class TmpfsVolume:
    path: str
    fs_type: str
    total_bytes: int
    used_bytes: int
    avail_bytes: int
    inodes_total: int = 0
    inodes_used: int = 0
    inodes_avail: int = 0
    quality: str = "ok"
    error: str = ""
    is_runtime: bool = False

    @property
    def used_frac(self) -> float:
        return self.used_bytes / self.total_bytes if self.total_bytes else 0.0

    @property
    def inodes_frac(self) -> float:
        return self.inodes_used / self.inodes_total if self.inodes_total else 0.0

    def to_dict(self) -> dict:
        return {"path": self.path, "fs_type": self.fs_type,
                "total_bytes": self.total_bytes, "used_bytes": self.used_bytes,
                "avail_bytes": self.avail_bytes,
                "inodes_total": self.inodes_total,
                "inodes_used": self.inodes_used,
                "inodes_avail": self.inodes_avail,
                "quality": self.quality, "error": self.error,
                "is_runtime": self.is_runtime,
                "used_pct": round(self.used_frac * 100, 1) if self.quality == "ok" else None,
                "inodes_supported": self.inodes_total > 0,
                "inodes_pct": round(self.inodes_frac * 100, 1) if self.inodes_total > 0 else None}


def _unescape(field: str) -> str:
    for needle, char in _ESCAPES.items():
        field = field.replace(needle, char)
    return field


def read_mounts_checked(proc_root: str | None = None) -> tuple[tuple, str | None]:
    """(montes, erro). Erro nomeado separa "sem montes" de "não consegui ler"."""
    try:
        raw = (Path(proc_root or paths.proc_root()) / "mounts").read_text()
    except OSError as exc:
        return (), f"{type(exc).__name__}: {exc}"
    out = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            out.append((_unescape(parts[1]), parts[2]))
    return tuple(out), None


def read_mounts(proc_root: str | None = None) -> tuple:
    """(mount_point, fs_type) por linha; () se o /proc não responder."""
    return read_mounts_checked(proc_root)[0]


def watched_volumes(*, proc_root: str | None = None, statvfs_fn=os.statvfs,
                    watched=None, mounts=None) -> tuple:
    runtime = discover_runtime()
    default_watch = watched is None
    if watched is None:
        watched = ("/tmp", "/dev/shm", runtime.path) if runtime.valid else ("/tmp", "/dev/shm")
    result = []
    if default_watch and not runtime.valid:
        result.append(TmpfsVolume(runtime.path, "unknown", 0, 0, 0,
                                  quality="error", error=runtime.reason, is_runtime=True))
    for mount, fs_type in (read_mounts(proc_root) if mounts is None else mounts):
        if fs_type != "tmpfs" or mount not in watched:
            continue
        try:
            vfs = statvfs_fn(mount)
        except OSError as exc:
            result.append(TmpfsVolume(mount, fs_type, 0, 0, 0,
                                      quality="error", error=str(exc),
                                      is_runtime=mount == runtime.path))
            continue
        frsize = vfs.f_frsize or vfs.f_bsize
        total = vfs.f_blocks * frsize
        used = (vfs.f_blocks - vfs.f_bfree) * frsize
        inodes_total = getattr(vfs, "f_files", 0)
        inodes_avail = getattr(vfs, "f_favail", 0)
        inodes_used = max(0, inodes_total - getattr(vfs, "f_ffree", inodes_total))
        result.append(TmpfsVolume(
            mount, fs_type, total, used, vfs.f_bavail * frsize,
            inodes_total, inodes_used, inodes_avail,
            quality="ok" if total > 0 else "partial",
            error="" if total > 0 else "capacidade total não comprovada",
            is_runtime=mount == runtime.path))
    return tuple(result)
