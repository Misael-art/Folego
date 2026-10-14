"""Read-only tree measurement for disk hygiene.

Contract: never follows symlinks, never crosses a mount point, never raises.
A path that cannot be read becomes a recorded error so one broken directory
cannot stop a whole hygiene pass, and a deadline bounds slow walks.
"""
import os
import stat as statmod
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TreeStat:
    path: str
    bytes: int
    files: int
    newest_ns: int
    errors: tuple
    truncated: bool


def _describe(err: OSError, path) -> str:
    return f"{path}: {err.strerror or err}"


def measure_tree(root, *, deadline_s: float | None = None,
                 clock=time.monotonic, scandir_fn=os.scandir) -> TreeStat:
    root = Path(root)
    errors: list[str] = []
    try:
        root_st = os.stat(root, follow_symlinks=False)
    except OSError as err:
        return TreeStat(str(root), 0, 0, 0, (_describe(err, root),), False)

    if root.is_symlink() or not statmod.S_ISDIR(root_st.st_mode):
        if root.is_symlink():
            return TreeStat(str(root), 0, 0, 0, ("refused: root is a symlink",), False)
        return TreeStat(str(root), root_st.st_size, 1, root_st.st_mtime_ns, (), False)

    root_dev = root_st.st_dev
    limit = None if deadline_s is None else clock() + deadline_s
    total = 0
    files = 0
    newest = root_st.st_mtime_ns
    truncated = False
    stack = [root]

    while stack:
        if limit is not None and clock() > limit:
            truncated = True
            break
        current = stack.pop()
        try:
            with scandir_fn(current) as it:
                entries = list(it)
        except OSError as err:
            errors.append(_describe(err, current))
            continue
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as err:
                errors.append(_describe(err, entry.path))
                continue
            newest = max(newest, st.st_mtime_ns)
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if st.st_dev != root_dev:
                    errors.append(f"{entry.path}: skipped cross-device directory")
                    continue
                stack.append(Path(entry.path))
                continue
            if statmod.S_ISREG(st.st_mode):
                total += st.st_size
                files += 1

    return TreeStat(str(root), total, files, newest, tuple(errors), truncated)
