"""Um olhar por cima do volume: o que é cada filho de nível-1.

Nada aqui decide — isto só chega honesto: tipo real (lstat; symlink é symlink),
dono, tamanho medido sem cruzar dispositivo, idade pelo arquivo mais novo da
árvore, monte lido do /proc/mounts (nunca por stat, que atravessaria um FUSE), e
os pids que têm algo aberto aqui.
"""
import os
import stat as statmod
import time
from dataclasses import dataclass
from pathlib import Path

from ...core.tmpfs import read_mounts
from ..disk.measure import measure_tree
from .holders import HolderIndex, holder_index

DAY_S = 86_400
KINDS = ((statmod.S_ISDIR, "dir"), (statmod.S_ISREG, "file"),
         (statmod.S_ISLNK, "symlink"), (statmod.S_ISSOCK, "socket"),
         (statmod.S_ISFIFO, "fifo"))


@dataclass(frozen=True)
class TmpfsEntry:
    path: str
    name: str
    volume: str
    kind: str = "other"
    uid: int = -1
    bytes: int = 0
    files: int = 0
    age_days: float = 0.0
    is_mount_point: bool = False
    under_mount: bool = False
    holder_pids: tuple = ()
    truncated: bool = False
    errors: tuple = ()


def kind_of(mode: int) -> str:
    for test, name in KINDS:
        if test(mode):
            return name
    return "other"


def _mount_state(path_str: str, mounts) -> tuple:
    points = {m for m, _ in mounts}
    return (path_str in points,
            any(m != path_str and m.startswith(path_str + os.sep) for m in points))


def entry_at(path, mounts, holders, *, volume: str, now=None, deadline_s: float = 10.0,
             lstat_fn=os.lstat, measure_fn=measure_tree) -> TmpfsEntry:
    now = time.time() if now is None else now
    p = Path(path)
    path_str = str(p)
    try:
        st = lstat_fn(path_str)
    except OSError as err:
        return TmpfsEntry(path_str, p.name, volume, "missing", -1, 0, 0, 0.0, False,
                          False, (), False, (f"{path_str}: {err.strerror or err}",))

    kind = kind_of(st.st_mode)
    is_point, under = _mount_state(path_str, mounts)
    size, files, newest_ns = 0, 0, st.st_mtime_ns
    truncated, errors = False, ()

    if kind == "dir" and not is_point and not under:
        stat = measure_fn(p, deadline_s=deadline_s)
        size, files = stat.bytes, stat.files
        newest_ns = stat.newest_ns or st.st_mtime_ns
        truncated, errors = stat.truncated, tuple(stat.errors)
    elif kind == "file":
        size, files = st.st_size, 1

    return TmpfsEntry(path_str, p.name, volume, kind, st.st_uid, size, files,
                      max(0.0, (now - newest_ns / 10**9) / DAY_S), is_point, under,
                      tuple(sorted(holders.pids_holding(path_str))), truncated, errors)


def inventory(volume, mounts, holders, *, now=None, deadline_s: float = 10.0,
              **kw) -> tuple:
    root = getattr(volume, "path", str(volume))
    try:
        names = sorted(os.listdir(root))
    except OSError:
        # Volume ilegível ou sumido devolve () — igual a volume vazio. A direção é
        # fail-closed (sem item, nada é liberado), mas NÃO é prova de limpeza: quem
        # apresenta (T11 `status`/`plan`, T13 aba) tem de dizer que leu o volume por
        # `read_mounts`/`statvfs` e que a lista de itens pode estar vazia por permissão.
        return ()
    return tuple(entry_at(os.path.join(root, name), mounts, holders, volume=str(root),
                          now=now, deadline_s=deadline_s, **kw) for name in names)


def scan_volume(volume, *, proc_root=None, now=None,
                deadline_s: float = 10.0) -> tuple:
    """Montes + holders + inventário de um volume: o tripé que CLI e liberação usam."""
    path = getattr(volume, "path", str(volume))
    mounts = read_mounts(proc_root)
    holders = holder_index(proc_root=proc_root, prefixes=(path,))
    return (mounts, holders,
            inventory(volume, mounts, holders, now=now, deadline_s=deadline_s))
