"""Índice de fd por caminho, dentro dos volumes que observamos.

Não segue nada, não abre nada: só readlink de /proc/<pid>/fd/*. Um alvo fora dos
prefixos não nos diz respeito, e um fd de outro usuário que não conseguimos ler é
pulado — a varredura tem de terminar mesmo quando metade da sessão é opaca.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from ... import paths
from ...core.tmpfs import WATCHED


@dataclass(frozen=True)
class HolderIndex:
    refs: dict
    proc_count: int
    fd_count: int

    def pids_holding(self, path: str) -> frozenset:
        prefix = str(path).rstrip(os.sep) or os.sep
        found: set[int] = set()
        for target, pids in self.refs.items():
            if target == prefix or target.startswith(prefix + os.sep):
                found.update(pids)
        return frozenset(found)


def _pid_dirs(root: Path, scandir_fn) -> list:
    try:
        with scandir_fn(root) as it:
            return sorted(int(e.name) for e in it if e.name.isdigit())
    except OSError:
        return []


def holder_index(*, proc_root: str | None = None, prefixes=WATCHED, pids=None,
                 scandir_fn=os.scandir, readlink_fn=os.readlink) -> HolderIndex:
    root = Path(proc_root or paths.proc_root())
    seen = (sorted(int(p) for p in pids) if pids is not None
            else _pid_dirs(root, scandir_fn))
    refs: dict[str, set[int]] = {}
    fd_count = 0
    for pid in seen:
        fd_dir = root / str(pid) / "fd"
        try:
            with scandir_fn(fd_dir) as it:
                names = sorted(e.name for e in it)
        except OSError:
            continue
        for name in names:
            try:
                target = readlink_fn(os.path.join(str(fd_dir), name))
            except OSError:
                continue
            fd_count += 1
            for prefix in prefixes:
                base = prefix.rstrip(os.sep) or os.sep
                if target == base or target.startswith(base + os.sep):
                    refs.setdefault(target, set()).add(pid)
                    break
    return HolderIndex({k: tuple(sorted(v)) for k, v in sorted(refs.items())},
                       len(seen), fd_count)
