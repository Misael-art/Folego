"""Disk hygiene M5 — /tmp expiry.

The Deck mounts tmpfs on /tmp sized at half of RAM, and tmpfs is backed by
memory: when it fills, *everything* that writes gets ENOSPC (bash history,
git, this app) even though the SSD has gigabytes free. Items there are
disposable by contract, so the safe policy is: only entries owned by this
user, only older than a floor, never through a symlink.
"""
import os
import shutil
import stat as statmod
import time
from dataclasses import dataclass
from pathlib import Path

from ...safely.audit import AuditLog
from .measure import measure_tree

DAY_S = 86_400


@dataclass(frozen=True)
class TmpItem:
    path: str
    bytes: int
    age_days: float


@dataclass(frozen=True)
class TmpPlan:
    root: str
    items: tuple
    kept: tuple
    total_bytes: int


@dataclass(frozen=True)
class ExpireResult:
    removed: tuple
    freed_bytes: int
    errors: tuple


def _lstat(path):
    return os.lstat(path)


def _size(path: Path) -> int:
    if path.is_dir():
        return measure_tree(path, deadline_s=10.0).bytes
    try:
        return _lstat(path).st_size
    except OSError:
        return 0


def plan_tmp(root, *, min_age_days: float = 3.0, now: float | None = None) -> TmpPlan:
    root = Path(root)
    now = time.time() if now is None else now
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError:
        return TmpPlan(str(root), (), (), 0)

    items = []
    kept = []
    for child in children:
        try:
            st = _lstat(child)
        except OSError:
            continue
        if statmod.S_ISLNK(st.st_mode):
            continue
        if st.st_uid != os.getuid():
            continue
        age_days = (now - st.st_mtime_ns / 10**9) / DAY_S
        if age_days < min_age_days:
            kept.append(str(child))
            continue
        items.append(TmpItem(str(child), _size(child), age_days))
    return TmpPlan(str(root), tuple(items), tuple(kept),
                   sum(i.bytes for i in items))


def _remove(path, *, is_dir: bool) -> None:
    if is_dir:
        shutil.rmtree(path)
    else:
        os.unlink(path)


def expire_tmp(root, *, min_age_days: float = 3.0, audit: AuditLog | None = None,
               remove_fn=_remove, now: float | None = None) -> ExpireResult:
    plan = plan_tmp(root, min_age_days=min_age_days, now=now)
    removed = []
    freed = 0
    errors = []
    for item in plan.items:
        path = Path(item.path)
        try:
            remove_fn(path, is_dir=path.is_dir())
        except OSError as err:
            errors.append(f"{path}: {err}")
            continue
        removed.append(item.path)
        freed += item.bytes

    if audit is not None:
        audit.append(kind="disk.tmp-expire", action_id="disk.tmp", outcome="expired",
                     targets=removed, risk="irreversible",
                     error="; ".join(errors) or None)
    return ExpireResult(tuple(removed), freed, tuple(errors))
