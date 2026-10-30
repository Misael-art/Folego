"""Decisão de destino a partir de mountinfo: RAM não é retenção.

R12: um caminho XDG não prova tipo de armazenamento. `tmpfs` sob a home, um
destino no mesmo monte da origem ou um monte que nem conhecemos são recusados —
retenção só vale onde libera a origem. As funções são puras para poderem ser
testadas com tabelas de monte de fixture; quem lê `/proc/mounts` é o chamador.
"""
import os
from dataclasses import dataclass

RAM_FS_TYPES = ("tmpfs", "ramfs")


@dataclass(frozen=True)
class DestinationVerdict:
    ok: bool
    reason: str
    mount: str | None = None
    fs_type: str | None = None
    same_mount_as_source: bool = False


def _normalize(mount_point: str) -> str:
    return str(mount_point).rstrip("/") or "/"


def covering_mount(path, mounts) -> tuple | None:
    """O monte mais profundo que contém `path`; None se a tabela não cobre."""
    path = _normalize(path)
    best = None
    for mount_point, fs_type in mounts:
        point = _normalize(mount_point)
        if point != "/" and path != point and not path.startswith(point + "/"):
            continue
        if best is None or len(point) > len(best[0]):
            best = (point, fs_type)
    return best


def destination_verdict(dest, *, source_mount: str | None = None,
                        mounts=(), stat_fn=os.stat) -> DestinationVerdict:
    """Recusa destino em RAM, mesmo monte da origem ou fora do que conhecemos."""
    dest = _normalize(dest)
    covering = covering_mount(dest, mounts)
    if covering is None:
        return DestinationVerdict(
            False, f"refused: {dest} não pertence a nenhum monte conhecido — sem "
                   "prova de armazenamento persistente")
    mount, fs_type = covering
    if fs_type in RAM_FS_TYPES:
        return DestinationVerdict(
            False, f"refused: o destino {dest} está em {mount} ({fs_type}), que é "
                   "RAM — reter ali não libera a origem", mount, fs_type)
    if source_mount is not None and _normalize(source_mount) == mount:
        return DestinationVerdict(
            False, f"refused: origem e destino estão no mesmo monte {mount}; "
                   "copiar não devolve capacidade à origem", mount, fs_type,
            same_mount_as_source=True)
    return DestinationVerdict(True, f"ok: destino em {mount} ({fs_type})",
                              mount, fs_type)


def mount_of(path, mounts, stat_fn=os.stat) -> str | None:
    """O monte que cobre `path`, do jeito que a tabela o nomeia."""
    covering = covering_mount(path, mounts)
    return covering[0] if covering else None
