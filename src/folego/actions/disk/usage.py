"""On-demand, bounded measurement of allocated bytes in a personal directory."""
from __future__ import annotations

import os
import stat
import time
from pathlib import Path

from ... import paths
from ...adapters.host_storage import local_mount, read_mountinfo

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_MAX_ENTRIES = 12_000
_MAX_DEPTH = 32
_DEADLINE_S = 2.0
_MAX_ROWS = 20


def _mount_id(fd: int) -> str:
    with open(f"/proc/self/fdinfo/{fd}", "rb") as stream:
        for line in stream.read(4096).splitlines():
            if line.startswith(b"mnt_id:"):
                return line.split()[1].decode("ascii")
    raise ValueError("identidade da montagem não disponível")


def _open_scope(home: Path, relative: Path, mount_id: str) -> int:
    fd = os.open(home, _DIRECTORY)
    try:
        for step in (None, *relative.parts):
            if step is not None:
                child = os.open(step, _DIRECTORY, dir_fd=fd)
                os.close(fd)
                fd = child
            if os.fstat(fd).st_uid != os.getuid() or _mount_id(fd) != mount_id:
                raise PermissionError("pasta em outra montagem ou de outro proprietário")
        return fd
    except BaseException:
        os.close(fd)
        raise


def inventory(directory=None, *, home=None, max_entries=_MAX_ENTRIES,
              deadline_s=_DEADLINE_S, clock=time.monotonic) -> dict:
    home = Path(home or Path.home())
    if directory is None:
        directory = home
    scope = Path(os.path.abspath(os.path.expanduser(directory)))
    try:
        real_home = home.resolve(strict=True)
        relative = scope.relative_to(home)
        folder = real_home / relative
        mounts = read_mountinfo(Path(paths.proc_root()))
        mount = local_mount(real_home, mounts)
        fd = _open_scope(real_home, relative, mount["mount_id"])
    except (OSError, ValueError, RuntimeError) as exc:
        return {"quality": "unknown", "reason": str(exc), "directory": str(scope), "items": []}

    mountpoints = {row["mount"] for row in mounts}
    uid = os.getuid()
    device = os.fstat(fd).st_dev
    until = clock() + deadline_s
    visited = skipped = 0
    truncated = False
    links = set()

    def can_read():
        if visited >= max_entries or clock() >= until:
            return False
        return True

    def measure(parent_fd, entry, path, row, depth):
        nonlocal skipped
        try:
            if str(path) in mountpoints:
                raise PermissionError("outra montagem")
            info = entry.stat(follow_symlinks=False)
            if info.st_uid != uid or info.st_dev != device:
                raise PermissionError("fora do escopo próprio")
            if stat.S_ISDIR(info.st_mode):
                if depth >= _MAX_DEPTH:
                    raise ValueError("profundidade máxima")
                child_fd = os.open(entry.name, _DIRECTORY, dir_fd=parent_fd)
                try:
                    actual = os.fstat(child_fd)
                    if ((actual.st_dev, actual.st_ino, actual.st_uid) != (device, info.st_ino, uid)
                            or _mount_id(child_fd) != mount["mount_id"]):
                        raise PermissionError("pasta alterada ou em outra montagem")
                    walk(child_fd, path, row, depth + 1)
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(info.st_mode):
                identity = (info.st_dev, info.st_ino)
                if info.st_nlink < 2 or identity not in links:
                    row["allocated_bytes"] += info.st_blocks * 512
                    row["files"] += 1
                    if info.st_nlink > 1:
                        links.add(identity)
        except (OSError, ValueError):
            skipped += 1
            row["partial"] = True

    def walk(parent_fd, path, row, depth):
        nonlocal truncated, visited
        with os.scandir(parent_fd) as children:
            for entry in children:
                if not can_read():
                    truncated = row["partial"] = True
                    return
                visited += 1
                measure(parent_fd, entry, path / entry.name, row, depth)
                if truncated:
                    return

    rows = []
    try:
        with os.scandir(fd) as children:
            for entry in children:
                if not can_read():
                    truncated = True
                    break
                visited += 1
                row = {"name": entry.name, "allocated_bytes": 0, "files": 0, "partial": False}
                measure(fd, entry, folder / entry.name, row, 0)
                if row["files"] or row["partial"]:
                    rows.append(row)
                if truncated:
                    break
    except OSError as exc:
        return {"quality": "unknown", "reason": str(exc), "directory": str(scope), "items": []}
    finally:
        os.close(fd)
    total = sum(row["allocated_bytes"] for row in rows)
    rows.sort(key=lambda row: (-row["allocated_bytes"], row["name"]))
    return {"quality": "partial" if truncated or skipped else "ok", "directory": str(scope),
            "mount": mount["mount"], "source": mount["source"], "type": mount["type"],
            "scanned_entries": visited, "skipped": skipped, "truncated": truncated,
            "allocated_bytes": total, "items": rows[:_MAX_ROWS], "total_items": len(rows),
            "reason": ("limite de leitura atingido" if truncated else
                       "entradas fora do escopo ou ilegíveis" if skipped else "")}
