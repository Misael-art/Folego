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


def _tree_age(child: Path, st, *, deadline_s: float = 10.0) -> tuple:
    """Idade pelo arquivo mais novo da árvore, não pelo filho direto.

    R01: o mtime do diretório não muda quando um arquivo já existente é regravado.
    Uma árvore só é lixo quando *nada* dentro dela foi tocado desde o piso. Leitura
    incompleta (erro/truncada) devolve `None`: não há prova suficiente para apagar.
    """
    if not statmod.S_ISDIR(st.st_mode):
        return st.st_mtime_ns, st.st_size, None
    stat = measure_tree(child, deadline_s=deadline_s)
    if stat.truncated or stat.errors:
        return stat.newest_ns, stat.bytes, (stat.errors or ("leitura truncada",))
    return max(st.st_mtime_ns, stat.newest_ns), stat.bytes, None


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
        newest_ns, size, incomplete = _tree_age(child, st)
        age_days = (now - newest_ns / 10**9) / DAY_S
        if incomplete or age_days < min_age_days:
            kept.append(str(child))
            continue
        items.append(TmpItem(str(child), size, age_days))
    return TmpPlan(str(root), tuple(items), tuple(kept),
                   sum(i.bytes for i in items))


def _remove(path, *, is_dir: bool) -> None:
    if is_dir:
        shutil.rmtree(path)
    else:
        os.unlink(path)


def expire_tmp(root, *, min_age_days: float = 3.0, audit: AuditLog | None = None,
               remove_fn=_remove, now: float | None = None) -> ExpireResult:
    this_now = time.time() if now is None else now
    plan = plan_tmp(root, min_age_days=min_age_days, now=this_now)
    removed = []
    freed = 0
    errors = []
    for item in plan.items:
        path = Path(item.path)
        # revalidar imediatamente antes do efeito: entre o plano e a remoção a
        # árvore pode ter recebido escrita (R01) ou sido trocada por outra
        try:
            st = _lstat(path)
            newest_ns, _size, incomplete = _tree_age(path, st)
            fresh_age = (this_now - newest_ns / 10**9) / DAY_S
        except OSError as err:
            errors.append(f"{path}: sumiu entre o plano e a remoção ({err})")
            continue
        if incomplete:
            errors.append(f"{path}: leitura incompleta na revalidação; preservado")
            continue
        if fresh_age < min_age_days:
            errors.append(f"{path}: recebeu escrita entre o plano e a remoção; "
                          f"preservado")
            continue
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
