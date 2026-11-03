"""Single GUI instance without Qt: one flock, visible failure, no silent second.

CLI mutations stay concurrent (they serialize in the coordinator); this lock is
only for the desktop UI. The holder PID is informative — the lock, not the PID,
is the authority. The file is left in place on release to avoid an unlink race;
the next process locks the same inode.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path

from .. import paths


class AlreadyRunning(Exception):
    def __init__(self, path: Path, holder_pid: int | None = None):
        self.path = Path(path)
        self.holder_pid = holder_pid
        detail = f"pid {holder_pid}" if holder_pid else "pid desconhecido"
        super().__init__(f"já existe uma instância do Fôlego ({detail})")


class InstanceLock:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.instance_lock_path()
        self._fd: int | None = None

    @property
    def locked(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        if self._fd is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = None
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                text = os.read(fd, 64).decode("ascii", "ignore").strip()
                holder = int(text) if text.isdigit() else None
            except OSError:
                holder = None
            os.close(fd)
            raise AlreadyRunning(self.path, holder) from None
        except OSError:
            os.close(fd)
            raise
        try:
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.fsync(fd)
        except OSError:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            raise
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
