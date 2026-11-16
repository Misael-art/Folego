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


def rename_noreplace(source: Path, target: Path) -> None:
    """Atomic Linux rename that refuses an existing destination."""
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as exc:
        raise OSError("renameat2 indisponível; origem preservada") from exc
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def write_atomic(path: Path, data: bytes, *, mode: int | None = None) -> WriteResult:
    """Write bytes so readers only ever see the old or new complete file.

    Same-dir tmp + O_EXCL + fsync + rename + dir-fsync: survives crashes and
    power loss without leaving a torn target file. `mode` lets private state
    files (sessions/exclusions) avoid the historical 0644 window.
    """
    existed = path.exists()
    file_mode = (stat.S_IMODE(path.stat().st_mode) if existed
                 else (0o644 if mode is None else mode))
    tmp = path.with_name(path.name + f"{TMP_MARKER}{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, file_mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if existed and stat.S_IMODE(path.stat().st_mode) != file_mode:
            os.chmod(tmp, file_mode)
        if mode is not None and stat.S_IMODE(tmp.stat().st_mode) != mode:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
        fsync_dir(path.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return WriteResult(sha256=sha256_bytes(data), size=len(data))
