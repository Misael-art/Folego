"""Liberar RAM de um tmpfs: copiar para a SSD, verificar, só então apagar.

A ordem é a segurança: toda recusa acontece antes de qualquer escrita, o clone é
conferido contra a origem, e o ledger registra o estado intermediário (``partial``)
em vez de deixá-lo ser inferido. Se a remoção falhar, nada foi perdido.
"""
import hashlib
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ... import paths
from ...safely import guard
from ...safely.hashing import sha256_file
from ..disk import planner
from .inventory import TmpfsEntry, entry_at
from .holders import holder_index
from .ledger import (ACTIVE_STATES, MAX_RETAINED_BYTES, STATE_PARTIAL, STATE_RELEASED)
from .policy import classify
from ...core.tmpfs import read_mounts

KIND = "tmpfs.release"
# /dev/shm é medido e exibido, nunca mutável: o guard blacklista o prefixo /dev
MUTABLE_VOLUMES = ("/tmp", "/run/user/1000")


@dataclass(frozen=True)
class ReleaseResult:
    ok: bool
    entry_id: str
    reason: str
    bytes: int = 0
    stored: str = ""
    sha256: str = ""
    freed_bytes: int = 0

    def to_dict(self) -> dict:
        return {"ok": self.ok, "entry_id": self.entry_id, "reason": self.reason,
                "bytes": self.bytes, "stored": self.stored, "sha256": self.sha256,
                "freed_bytes": self.freed_bytes}


def _stamp(now: float) -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))


def _entry_id(now: float) -> str:
    return f"{int(now)}-{uuid.uuid4().hex[:8]}"


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:60] or "unnamed"


def default_allowed_roots(home=None) -> list:
    home = Path(home) if home else Path.home()
    return planner.default_allowed_roots(home) + [Path(p) for p in MUTABLE_VOLUMES]


def tree_digest(path: Path) -> tuple[str, int]:
    """Conteúdo e tamanho, em ordem estável: mtime e donos não mudam o digest."""
    root = Path(path)
    h = hashlib.sha256()
    total = 0
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            h.update(f"L:{rel}:{os.readlink(p)}\n".encode())
        elif p.is_file():
            total += p.stat().st_size
            h.update(f"F:{rel}:{sha256_file(p)}\n".encode())
    return h.hexdigest(), total


def _fresh_entry(path: str, *, volume: str = "", proc_root: str | None = None,
                 now: float | None = None) -> TmpfsEntry:
    """Re-derivado no momento da mutação: o plano pode estar superado."""
    mounts = read_mounts(proc_root)
    holders = holder_index(prefixes=(volume or path,), proc_root=proc_root)
    return entry_at(path, mounts, holders, volume=volume, now=now)


def _refuse(entry_id: str, reason: str) -> ReleaseResult:
    return ReleaseResult(False, entry_id, reason)


def release_item(plan, item, *, ledger, dest_root=None, audit=None, confirm=False,
                 entry_fn=_fresh_entry, statvfs_fn=os.statvfs, now: float | None = None,
                 allowed_roots=None, remove_fn=None, proc_root=None) -> ReleaseResult:
    now = time.time() if now is None else now
    entry_id = _entry_id(now)
    src = Path(item.path)
    if not confirm:
        return _refuse(entry_id, "refused: liberar RAM exige --confirmar; "
                                 "nada foi alterado")

    held = ledger.find(item.path)
    if held is not None and held.state in ACTIVE_STATES:
        return _refuse(entry_id, f"refused: {item.path} já está no ledger como "
                                 f"{held.state} ({held.entry_id}); a correção é "
                                 "manual (restore ou purge por id)")

    fresh = entry_fn(str(src), volume=item.volume, proc_root=proc_root, now=now)
    verdict = classify(fresh, plan.policy)
    if not verdict.ok:
        return _refuse(entry_id, f"refused: {verdict.reason}")

    roots = list(allowed_roots) if allowed_roots else default_allowed_roots()
    guard_verdict = guard.validate_target(src, roots)
    if not guard_verdict.ok:
        return _refuse(entry_id, guard_verdict.reason)

    dest_root = Path(dest_root) if dest_root else paths.tmp_quarantine_dir()
    dest = dest_root / _stamp(now) / _sanitize(src.name)
    # o pai do destino, não o destino: num destino ainda inexistente o guard avaliaria
    # o diretório de timestamp, que também não existe — e a primeira liberação da vida
    # seria recusada para sempre. O prefixo blacklisted pega o destino de verdade.
    probe = dest_root if dest_root.exists() else dest_root.parent
    dest_verdict = guard.validate_target(probe, roots)
    if not dest_verdict.ok:
        return _refuse(entry_id, f"refused: o destino de retenção não é gravável "
                                 f"em {probe}: {dest_verdict.reason}")

    if dest.exists():
        return _refuse(entry_id, f"refused: {dest} já existe — itens homônimos "
                                 "colidem nesse destino, e o clone já ledgerado "
                                 "seria pisado")

    vfs = statvfs_fn(str(probe))
    if vfs.f_bavail * vfs.f_frsize < 2 * item.bytes:
        return _refuse(entry_id, f"refused: o destino não tem folga para copiar "
                                 f"{item.bytes} bytes antes de apagar a origem")

    if ledger.retained_bytes() + item.bytes > MAX_RETAINED_BYTES:
        oldest = ledger.oldest()
        return _refuse(entry_id, f"refused: reter mais {item.bytes} bytes estouraria "
                                 f"o orçamento de {MAX_RETAINED_BYTES}; a candidata "
                                 f"a expirar é {oldest.entry_id} ({oldest.src})")

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, symlinks=True)
        else:
            shutil.copy2(src, dest)
    except OSError as err:
        _quiet_remove(dest)
        return _refuse(entry_id, f"refused: a cópia falhou ({err.strerror or err}); "
                                 "a origem está intacta")

    source_digest, _ = tree_digest(src)
    clone_digest, clone_bytes = tree_digest(dest)
    if source_digest != clone_digest:
        _quiet_remove(dest)
        return _refuse(entry_id, "refused: o digest do clone difere da origem; "
                                 "nada foi apagado")

    # o clone existe e o original ainda está lá: esse estado é registrado, não inferido
    partial_event = _audit(audit, entry_id, STATE_PARTIAL, [str(src), str(dest)],
                           plan_digest=plan.digest)
    ledger.append(**_fields(entry_id, item, fresh, dest, clone_digest, clone_bytes,
                            STATE_PARTIAL, partial_event))
    _sync_dir(dest.parent)

    remove = remove_fn or _remove
    try:
        remove(src)
    except OSError as err:
        _audit(audit, entry_id, STATE_PARTIAL, [str(src), str(dest)],
               plan_digest=plan.digest,
               error=f"a origem não pôde ser removida: {err.strerror or err}")
        return ReleaseResult(False, entry_id,
                             f"refused: o clone está em {dest} e registrado como "
                             f"partial; a origem não foi removida "
                             f"({err.strerror or err}); nada foi perdido",
                             bytes=item.bytes, stored=str(dest), sha256=clone_digest,
                             freed_bytes=0)

    released_event = _audit(audit, entry_id, STATE_RELEASED, [str(src), str(dest)],
                            plan_digest=plan.digest)
    ledger.append(**_fields(entry_id, item, fresh, dest, clone_digest, clone_bytes,
                            STATE_RELEASED, released_event))
    return ReleaseResult(True, entry_id, "ok", bytes=item.bytes, stored=str(dest),
                         sha256=clone_digest, freed_bytes=item.bytes)


def _sync_dir(path: Path) -> None:
    """fsync do diretório: é o que torna a linha `partial` verdadeira depois de um tombo."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _quiet_remove(path: Path) -> None:
    try:
        _remove(path)
    except OSError:
        pass  # o clone falho não apaga nada de valor; a recusa já foi reportada


def _fields(entry_id, item, fresh, dest, digest, size, state, event_id) -> dict:
    return {
        "entry_id": entry_id, "src": item.path, "volume": item.volume,
        "stored": str(dest), "bytes": size, "sha256": digest,
        "age_days": fresh.age_days, "matched_pattern": item.matched,
        "holder_pids": tuple(fresh.holder_pids), "state": state,
        "action_id": KIND, "audit_event_id": event_id or "",
    }


def _audit(audit, entry_id, outcome, targets, *, plan_digest=None,
           error=None) -> str:
    if audit is None:
        return ""
    return audit.append(kind=KIND, action_id=entry_id, outcome=outcome,
                        targets=targets, risk="reversible",
                        plan_digest=plan_digest, error=error)["event_id"]
