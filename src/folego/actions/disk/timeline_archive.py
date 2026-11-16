"""Manual, journaled retention for a completed boot's own diagnostic log."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from ... import paths
from ...adapters.host_storage import local_mount, read_mountinfo
from ...adapters.host_timeline import (
    _BOOT_ID, _MAX_FILES, _PER_BOOT_LIMIT, _entries, _private_directory, _valid_sample,
    archive_directory,
)
from ...core.sessions import read_boot_id
from ...orchestration import ActionPlan, ActionResult, Outcome, ResourceIdentity
from ...safely.atomicfile import fsync_dir, rename_noreplace

ACTION = "disk.timeline-archive"
_ARCHIVE_FILES = 256
_ARCHIVE_BYTES = 128 * 1024 ** 2


def candidates(directory: Path) -> list[dict]:
    current = read_boot_id()
    if not _BOOT_ID.fullmatch(current):
        raise ValueError("boot atual não comprovado")
    _private_directory(directory)
    result = []
    for path in _entries(directory, _MAX_FILES + 1):
        if path.stem == current or path.suffix != ".jsonl" or not _BOOT_ID.fullmatch(path.stem):
            continue
        info = path.lstat()
        if (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and 0 < info.st_size <= _PER_BOOT_LIMIT):
            result.append({"boot_id": path.stem, "bytes": info.st_size, "last_modified": info.st_mtime})
    return sorted(result, key=lambda row: row["last_modified"])


def _log_evidence(path: Path, boot_id: str) -> dict:
    def identity(info):
        return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or not 0 < info.st_size <= _PER_BOOT_LIMIT):
            raise ValueError("arquivo de histórico inválido ou não privado")
        raw = stream.read(_PER_BOOT_LIMIT + 1)
        if (len(raw) != info.st_size or not raw.endswith(b"\n")
                or identity(os.fstat(stream.fileno())) != identity(info)
                or identity(path.lstat()) != identity(info)):
            raise ValueError("arquivo mudou ou contém final incompleto")
    for line in raw.splitlines():
        row = json.loads(line)
        if not _valid_sample(row) or row["boot_id"] != boot_id:
            raise ValueError("amostra inválida ou de outro boot; arquivo preservado")
    return {"stat": identity(info), "sha256": hashlib.sha256(raw).hexdigest()}


def review(directory: Path, boot_id: str) -> ActionPlan:
    current = read_boot_id()
    if not _BOOT_ID.fullmatch(current) or not _BOOT_ID.fullmatch(boot_id) or boot_id == current:
        raise ValueError("selecione um boot anterior comprovado")
    directory_info = _private_directory(directory)
    _entries(directory, _MAX_FILES + 1)
    if directory.resolve(strict=True) != directory:
        raise ValueError("caminho de histórico com ancestral simbólico")
    mounts = read_mountinfo(Path(paths.proc_root()))
    source_mount = local_mount(directory, mounts)
    archive = archive_directory(directory)
    name = boot_id + ".jsonl"
    source, target = directory / name, archive / name
    if local_mount(source, mounts) != source_mount or local_mount(archive, mounts) != source_mount:
        raise ValueError("arquivo ou destino em outra montagem")
    evidence = _log_evidence(source, boot_id)
    if evidence["stat"][0] != directory_info.st_dev:
        raise ValueError("arquivo de histórico em outro dispositivo")
    if archive.exists() or archive.is_symlink():
        if _private_directory(archive).st_dev != directory_info.st_dev:
            raise ValueError("destino de histórico em outro dispositivo")
        total = evidence["stat"][2]
        entries = _entries(archive, _ARCHIVE_FILES - 1)
        for path in entries:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or path == target):
                raise ValueError("arquivo arquivado já existe ou inventário inesperado")
            total += info.st_size
        if total > _ARCHIVE_BYTES:
            raise ValueError("orçamento do arquivo histórico atingido")
    identity = ResourceIdentity("path", str(source), {
        **evidence, "directory": [directory_info.st_dev, directory_info.st_ino],
        "mount_id": source_mount["mount_id"], "active_boot": current,
    })
    return ActionPlan(ACTION, identity, {"boot_id": boot_id, "archive": str(target)})


def archive(directory: Path, plan: ActionPlan, coordinator) -> ActionResult:
    if (plan.action != ACTION or plan.target.kind != "path"
            or not isinstance(plan.params.get("boot_id"), str)
            or not isinstance(plan.params.get("archive"), str)):
        raise ValueError("plano de arquivamento inválido")

    def execute(committed: ActionPlan):
        source = Path(committed.target.key)
        target = Path(committed.params["archive"])
        try:
            checked = review(directory, committed.params["boot_id"])
            if checked.target != committed.target or checked.params != committed.params:
                raise ValueError("histórico ou montagem mudou desde a revisão")
        except (OSError, ValueError) as exc:
            return ActionResult(ACTION, Outcome.REFUSED, committed.operation_id,
                                target_key=committed.target.key, reason=str(exc))
        target.parent.mkdir(mode=0o700, exist_ok=True)
        _private_directory(target.parent)
        fsync_dir(target.parent.parent)
        rename_noreplace(source, target)
        fsync_dir(target.parent)
        fsync_dir(directory)
        observed = _log_evidence(target, committed.params["boot_id"])
        expected = committed.target.detail
        if observed["stat"][:4] != list(expected["stat"][:4]) or observed["sha256"] != expected["sha256"]:
            raise ValueError("identidade ou conteúdo do histórico divergiu após arquivar")
        return ActionResult(ACTION, Outcome.OK, committed.operation_id,
                            target_key=committed.target.key, reason="histórico preservado",
                            effects={"boot_id": committed.params["boot_id"], "archive": str(target),
                                     "sha256": observed["sha256"]})

    return coordinator.run(plan, execute)
