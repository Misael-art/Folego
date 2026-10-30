"""Bounded, read-only evidence for manual quarantine review.

This snapshot detects replacement and changes before entry. It is not a lease
against future writers and never authorizes automatic cleanup.
"""
import hashlib
import json
import os
import stat
import time
from pathlib import Path

from ...orchestration.models import ActionPlan, ResourceIdentity

PROTECTED_NAMES = {".git", ".ssh", ".gnupg", "credentials", "wallet.dat", "models", "volumes"}
PROTECTED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".qcow2", ".vmdk", ".gguf", ".safetensors", ".pem", ".key"}


def identity(path, *, max_entries=10000, timeout_s=2.0):
    path = Path(os.path.abspath(os.path.expanduser(str(path))))
    ancestors = []
    for parent in reversed((path, *path.parents)):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise PermissionError("refused: ancestral/raiz simbólico")
        ancestors.append((str(parent), info.st_dev, info.st_ino))
    info = path.lstat()
    # Linux mount IDs distinguish bind mounts even on the same device.
    table = Path("/proc/self/mountinfo").read_text()
    covering = None
    for line in table.splitlines():
        fields = line.split()
        point = fields[4].replace("\\040", " ").replace("\\134", "\\")
        if str(path) == point or str(path).startswith(point.rstrip("/") + "/"):
            if covering is None or len(point) > len(covering[1]):
                covering = (fields[0], point, line)
        if point != str(path) and point.startswith(str(path) + "/"):
            raise PermissionError("refused: árvore contém montagem")
    if covering is None:
        raise PermissionError("refused: identidade da montagem desconhecida")
    deadline = time.monotonic() + timeout_s
    rows = []
    stack = [path]
    while stack:
        current = stack.pop()
        if len(rows) >= max_entries or time.monotonic() > deadline:
            raise PermissionError("refused: orçamento da revisão esgotado; evidência incompleta")
        item = current.lstat()
        if (current.name in PROTECTED_NAMES or current.suffix.lower() in PROTECTED_SUFFIXES
                or item.st_uid != os.getuid()
                or item.st_dev != info.st_dev
                or not (stat.S_ISDIR(item.st_mode) or stat.S_ISREG(item.st_mode))):
            raise PermissionError("refused: conteúdo protegido, especial, simbólico ou de outro dono")
        rows.append((str(current.relative_to(path)), item.st_dev, item.st_ino,
                     item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns))
        if stat.S_ISDIR(item.st_mode):
            with os.scandir(current) as entries:
                # Bounded enumeration; never materialize an unlimited directory.
                for entry in entries:
                    stack.append(Path(entry.path))
                    if len(stack) + len(rows) > max_entries:
                        raise PermissionError("refused: diretório excede orçamento de revisão")
    digest = hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest()
    return ResourceIdentity("path", str(path), {
        "dev": info.st_dev, "ino": info.st_ino, "tree_digest": digest,
        "mount_id": covering[0], "mount_record": covering[2],
        "ancestors": ancestors, "entries": len(rows)})


def plan_quarantine(path, book):
    path = Path(os.path.abspath(os.path.expanduser(str(path))))
    book._check(path)
    target = identity(path)
    return ActionPlan("disk.quarantine", target, {},
                      notes=("revisão manual; quarentena reversível; nenhuma autorização automática",))
