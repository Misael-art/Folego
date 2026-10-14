"""Path safety kernel: what may be mutated, and what must never be touched.

All checks are pure (no mutation, no network); stat_fn is injectable so
ownership rules are testable without root.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

BLACKLIST_PREFIXES = (
    "/mnt", "/run/media", "/media", "/etc", "/usr", "/var", "/boot",
    "/sys", "/proc", "/dev", "/root", "/srv", "/opt", "/bin", "/sbin", "/lib",
)


@dataclass(frozen=True)
class GuardVerdict:
    ok: bool
    reason: str


def _default_stat(path: Path):
    return os.stat(path)


def _under(path_str: str, root: Path) -> bool:
    root_str = str(root)
    return path_str == root_str or path_str.startswith(root_str + os.sep)


def validate_target(
    path: str | Path,
    allowed_roots: Sequence[Path],
    *,
    stat_fn: Callable[[Path], object] = _default_stat,
) -> GuardVerdict:
    p = Path(path)
    s = str(p)

    for prefix in BLACKLIST_PREFIXES:
        if s == prefix or s.startswith(prefix + os.sep):
            return GuardVerdict(False, f"refused: path is under blacklisted prefix {prefix}")

    if p.is_symlink():
        return GuardVerdict(False, "refused: mutation targets must not be symlinks")

    resolved = p.resolve()
    roots = [r.resolve() for r in allowed_roots]
    if not any(_under(str(resolved), r) for r in roots):
        return GuardVerdict(False, "refused: resolved path is outside every allowed root")

    if p.exists():
        if getattr(stat_fn(p), "st_uid", None) != os.getuid():
            return GuardVerdict(False, "refused: file owner is not the current user")
        return GuardVerdict(True, "ok")

    parent = p.parent
    if not parent.is_dir():
        return GuardVerdict(False, "refused: parent directory does not exist")
    if not os.access(parent, os.W_OK):
        return GuardVerdict(False, "refused: parent directory is not writable")
    return GuardVerdict(True, "ok")
