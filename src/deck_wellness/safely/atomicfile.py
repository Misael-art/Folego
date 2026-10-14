import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .hashing import sha256_bytes

TMP_MARKER = ".deckwellness."


@dataclass(frozen=True)
class WriteResult:
    sha256: str
    size: int


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_atomic(path: Path, data: bytes) -> WriteResult:
    """Write bytes so readers only ever see the old or new complete file.

    Same-dir tmp + O_EXCL + fsync + rename + dir-fsync: survives crashes and
    power loss without leaving a torn target file.
    """
    existed = path.exists()
    mode = stat.S_IMODE(path.stat().st_mode) if existed else 0o644
    tmp = path.with_name(path.name + f"{TMP_MARKER}{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if existed and stat.S_IMODE(path.stat().st_mode) != mode:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
        fsync_dir(path.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return WriteResult(sha256=sha256_bytes(data), size=len(data))
