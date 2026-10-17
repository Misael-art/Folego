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
from .ledger import (ACTIVE_STATES, LedgerRecord, MAX_RETAINED_BYTES, RETENTION_DAYS,
                     STATE_DROPPED, STATE_EXPIRED, STATE_PARTIAL, STATE_RELEASED,
                     STATE_RESTORED)
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
    """Conteúdo e tamanho, em ordem estável: mtime e donos não mudam o digest.

    O ramo de arquivo não é decoração: `rglob("*")` não desce num arquivo, então sem
    ele um item `kind == "file"` — e `/tmp/tmp*` está na allow-list default — daria o
    SHA-256 do vazio nas duas pontas, a verificação viraria tautologia e o ledger
    gravaria `bytes: 0`, furando o teto de retenção.
    """
    root = Path(path)
    if root.is_file():
        return sha256_file(root), root.stat().st_size
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
        # o reason do classify JÁ vem prefixado com "refused: " — prefixar de novo é
        # a mensagem que o usuário leria no stderr da T11/T12
        return _refuse(entry_id, verdict.reason)

    roots = list(allowed_roots) if allowed_roots else default_allowed_roots()
    guard_verdict = guard.validate_target(src, roots)
    if not guard_verdict.ok:
        return _refuse(entry_id, guard_verdict.reason)

    # o portão usa o MAIOR dos dois tamanhos: o plano pode estar superado e a cópia
    # vai levar o que a árvore tem agora, não o que ela tinha quando o plano nasceu
    gate = max(item.bytes, fresh.bytes)
    dest_root = Path(dest_root) if dest_root else paths.tmp_quarantine_dir()
    dest = dest_root / _stamp(now) / _sanitize(src.name)
    # o pai do destino, não o destino: num destino ainda inexistente o guard avaliaria
    # o diretório de timestamp, que também não existe — e a primeira liberação da vida
    # seria recusada para sempre. O prefixo blacklisted pega o destino de verdade.
    probe = dest_root if dest_root.exists() else dest_root.parent
    dest_verdict = guard.validate_target(probe, roots)
    if not dest_verdict.ok:
        return _refuse(entry_id, f"{dest_verdict.reason} — o destino de retenção "
                                 f"é {probe}")

    if dest.exists():
        return _refuse(entry_id, f"refused: {dest} já existe — itens homônimos "
                                 "colidem nesse destino, e o clone já ledgerado "
                                 "seria pisado")

    vfs = statvfs_fn(str(probe))
    if vfs.f_bavail * vfs.f_frsize < 2 * gate:
        return _refuse(entry_id, f"refused: o destino não tem folga para copiar "
                                 f"{gate} bytes antes de apagar a origem")

    restantes = MAX_RETAINED_BYTES - ledger.retained_bytes()
    if gate > restantes:
        oldest = ledger.oldest()
        cand = (f"a candidata a expirar é {oldest.entry_id} ({oldest.src})" if oldest
                else "nada está retido — o item sozinho passa do teto")
        return _refuse(entry_id, f"refused: reter mais {gate} bytes estouraria o "
                                 f"orçamento de {MAX_RETAINED_BYTES}; {cand}")

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

    # o digest relê a ORIGEM: entre o copy e aqui o agente pode ter apagado o que
    # estava sendo copiado. Sem este try, o clone ficaria na SSD sem linha de ledger
    # — byte retido que nem `retained_bytes()` nem a T13 jamais veriam.
    try:
        source_digest, _ = tree_digest(src)
        clone_digest, clone_bytes = tree_digest(dest)
    except OSError as err:
        _quiet_remove(dest)
        return _refuse(entry_id, f"refused: o digest não pôde ser lido "
                                 f"({err.strerror or err}); nada foi apagado")

    if source_digest != clone_digest:
        _quiet_remove(dest)
        return _refuse(entry_id, "refused: o digest do clone difere da origem; "
                                 "nada foi apagado")

    # o clone existe e o original ainda está lá: esse estado é registrado, não inferido
    partial_event = _audit(audit, entry_id, STATE_PARTIAL, [str(src), str(dest)],
                           plan_digest=plan.digest)
    ledger.append(**_fields(entry_id, item, fresh, dest, clone_digest, clone_bytes,
                            STATE_PARTIAL, partial_event))
    _sync_tree(dest)
    _sync_fd(dest.parent)

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
                             bytes=clone_bytes, stored=str(dest), sha256=clone_digest,
                             freed_bytes=0)

    released_event = _audit(audit, entry_id, STATE_RELEASED, [str(src), str(dest)],
                            plan_digest=plan.digest)
    ledger.append(**_fields(entry_id, item, fresh, dest, clone_digest, clone_bytes,
                            STATE_RELEASED, released_event))
    return ReleaseResult(True, entry_id, "ok", bytes=clone_bytes, stored=str(dest),
                         sha256=clone_digest, freed_bytes=clone_bytes)


def _sync_fd(path: Path) -> None:
    """fsync de um caminho (arquivo OU diretório): O_RDONLY + fsync funciona nos dois."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_tree(path: Path) -> None:
    """fsync de cada arquivo copiado, antes do fsync do diretório.

    O `tree_digest` leu a cópia pela page cache, então "verificado igual" ainda não
    quer dizer "chegou à SSD" — e é logo depois dele que a origem é apagada. O
    fsync do diretório sozinho não fecha essa janela.
    """
    arquivos = [path] if path.is_file() else sorted(path.rglob("*"))
    for p in arquivos:
        if p.is_file():
            _sync_fd(p)


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


def _audit(audit, entry_id, outcome, targets, *, plan_digest=None, error=None,
           kind=KIND, risk="reversible") -> str:
    if audit is None:
        return ""
    return audit.append(kind=kind, action_id=entry_id, outcome=outcome,
                        targets=targets, risk=risk,
                        plan_digest=plan_digest, error=error)["event_id"]


RESTORE_KIND = "tmpfs.restore"
EXPIRE_KIND = "tmpfs.expire"


@dataclass(frozen=True)
class RestoreResult:
    ok: bool
    entry_id: str
    reason: str
    bytes: int = 0
    restored_to: str = ""


@dataclass(frozen=True)
class ExpireResult:
    ok: bool
    reason: str
    victims: tuple[str, ...] = ()
    freed_bytes: int = 0
    errors: tuple[str, ...] = ()


def _foreign_mount(path: str, mounts, volume: str) -> str | None:
    """O monte que *contém* o destino tem de ser o próprio volume, e nada pode
    estar montado *dentro* dele.

    É a R1 lida ao contrário: `/run` e `/run/user/1000` são ambos tmpfs montados, e
    um destino dentro do volume é legítimo; o que não é legítimo é o caminho cair
    sob um monte que não é o volume medido (um `private/tmp` de systemd, um portal
    novo) ou escrever por cima de um monte que apareceu dentro dele.
    """
    points = [m for m, _ in mounts]
    covering = [m for m in points if path == m or path.startswith(m + os.sep)]
    deepest = max(covering, key=len, default=None)
    if deepest is not None and deepest != volume:
        return deepest
    return next((m for m in points if m.startswith(path + os.sep)), None)


def restore_item(record_or_id, *, ledger, audit=None, confirm=False,
                 statvfs_fn=os.statvfs, allowed_roots=None,
                 now: float | None = None, mounts_fn=read_mounts) -> RestoreResult:
    now = time.time() if now is None else now
    if not confirm:
        return RestoreResult(False, str(record_or_id),
                             "refused: restaurar exige --confirmar; nada foi alterado")
    record = record_or_id if isinstance(record_or_id, LedgerRecord) \
        else ledger.find(str(record_or_id))
    if record is None:
        return RestoreResult(False, str(record_or_id), "refused: entrada desconhecida "
                                                       "no ledger")
    if record.state not in (STATE_RELEASED, STATE_PARTIAL):
        return RestoreResult(False, record.entry_id,
                             f"refused: a entrada está {record.state}")
    entry_id = record.entry_id

    original = Path(record.src)
    stored_path = Path(record.stored)
    if original.exists():
        return RestoreResult(False, entry_id,
                             f"refused: {original} já existe, nada é sobrescrito")
    if not stored_path.exists():
        return RestoreResult(False, entry_id, "refused: o payload retido sumiu da SSD")

    roots = list(allowed_roots) if allowed_roots else default_allowed_roots()
    verdict = guard.validate_target(original, roots)
    if not verdict.ok:
        return RestoreResult(False, entry_id, verdict.reason)
    mount = _foreign_mount(str(original.resolve()), mounts_fn(), record.volume)
    if mount is not None:
        return RestoreResult(False, entry_id,
                             f"refused: {original} cruza o monte {mount}, que não é "
                             f"o volume {record.volume}")

    volume = Path(record.volume)
    stat = statvfs_fn(str(volume))
    if stat.f_bavail * stat.f_frsize < record.bytes:
        return RestoreResult(False, entry_id,
                             f"refused: {volume} não tem espaço para devolver "
                             f"{record.bytes} bytes")

    # A certidão antes da escrita: `record.sha256` é o digest do clone tal como a
    # liberação o certificou. Ler o retido só *depois* da cópia — como este plano
    # fazia — torna a verificação da volta tautológica no único caso que importa:
    # payload apodrecido na SSD produz destino apodrecido no volume, os dois digests
    # batem, e o `restore` diz "ok" enquanto entrega lixo. Assim, a recusa vem antes
    # de qualquer byte escrito no volume.
    try:
        stored_digest, _ = tree_digest(stored_path)
    except OSError as err:
        return RestoreResult(False, entry_id,
                             f"refused: o retido não pôde ser lido "
                             f"({err.strerror or err}); nada foi alterado")
    if stored_digest != record.sha256:
        return RestoreResult(False, entry_id,
                             "refused: o digest do retido difere do certificado no "
                             "ledger; nada foi devolvido")

    try:
        original.parent.mkdir(parents=True, exist_ok=True)
        if stored_path.is_dir():
            shutil.copytree(stored_path, original, symlinks=True)
        else:
            shutil.copy2(stored_path, original)
    except OSError as err:
        _quiet_remove(original)
        return RestoreResult(False, entry_id, f"refused: a cópia de volta falhou "
                                              f"({err.strerror or err}); a SSD mantém o item")

    back_digest, size = tree_digest(original)
    if back_digest != stored_digest:
        _quiet_remove(original)
        return RestoreResult(False, entry_id,
                             "refused: o digest da volta difere do retido; o clone "
                             "da SSD foi mantido")

    _quiet_remove(stored_path)
    # §7: a linha do ledger e o evento de auditoria são a mesma transição, e a
    # linha aponta para o evento — o `_audit` da T9 já devolve o `event_id`.
    # A ordem é apagar → auditar → registrar: no outro sentido, uma falha entre o
    # registrar e o apagar deixaria clone na SSD com o ledger dizendo `restored`,
    # ou seja, byte retido que nem `retained_bytes()` nem o `expire` jamais veem —
    # o clone órfão do §6 espelhado. Assim como está, o pior caso é o orçamento
    # contar de mais, e o `expire` já trata payload sumido como erro relatado.
    event_id = _audit(audit, entry_id, STATE_RESTORED,
                      [record.stored, str(original)], kind=RESTORE_KIND)
    _transition(ledger, record, STATE_RESTORED, RESTORE_KIND, event_id, bytes=size)
    return RestoreResult(True, entry_id, "ok", bytes=size, restored_to=str(original))


def _transition(ledger, record: LedgerRecord, state: str, action_id: str,
                event_id: str = "", **changes):
    """Uma linha nova, com o relógio de agora: o `ts` do registro é a origem, não a transição.

    O `audit_event_id` é o da *desta* transição, passado por quem chamou: a spec §7
    quer o campo preenchido e foi exatamente isso que `test_the_ledger_line_points_at_its_own_audit_event`
    pinou na T9. Deixar `""` aqui faria a linha `restored`/`expired` apontar para
    nada enquanto o evento correspondente existe em `audit.jsonl`.
    """
    ledger.append(**{**record.to_dict(), **changes, "ts": "", "state": state,
                     "action_id": action_id, "audit_event_id": event_id or ""})


def expire_over_budget(*, ledger, audit=None, days: float = RETENTION_DAYS,
                       max_bytes: int = MAX_RETAINED_BYTES, confirm=False,
                       irreversible=False, now: float | None = None,
                       allowed_roots=None, remove_fn=_remove) -> ExpireResult:
    now = time.time() if now is None else now
    victims = ledger.over_budget(days=days, max_bytes=max_bytes, now=now)
    listed = ", ".join(f"{r.entry_id} ({r.bytes} bytes, {r.src})" for r in victims)

    if not victims:
        return ExpireResult(True, "nada vencido: a retenção cabe no orçamento "
                                  f"({days:g} d / {max_bytes} bytes)")
    if confirm != irreversible:
        missing = "--irreversivel" if confirm else "--confirmar"
        return ExpireResult(False, f"refused: expirar é irreversível e exige "
                                   f"--confirmar e --irreversivel (faltou {missing}); "
                                   f"nada foi alterado")
    if not confirm:
        # o dry-run devolve a lista que um --confirmar --irreversivel apagaria, no
        # mesmo formato: é assim que o usuário audita antes de confiar no ato
        return ExpireResult(True, f"dry-run: expiraria {len(victims)} entrada(s): "
                                  f"{listed}; nada foi alterado",
                                  tuple(r.entry_id for r in victims))

    roots = list(allowed_roots) if allowed_roots else default_allowed_roots()
    freed, errors, done = 0, [], []
    for record in victims:
        payload = Path(record.stored)
        verdict = guard.validate_target(payload, roots)
        if not verdict.ok:
            errors.append(f"{record.entry_id}: {verdict.reason}")
            continue
        try:
            if payload.exists():
                remove_fn(payload)
            else:
                errors.append(f"{record.entry_id}: o payload {payload} já não existia")
        except OSError as err:
            errors.append(f"{record.entry_id}: {err.strerror or err}")
            continue
        freed += record.bytes
        done.append(record.entry_id)
        event_id = _audit(audit, record.entry_id, STATE_EXPIRED, [record.stored],
                          kind=EXPIRE_KIND, risk="irreversible")
        _transition(ledger, record, STATE_EXPIRED, EXPIRE_KIND, event_id)
    return ExpireResult(True, f"expiradas {len(done)} entrada(s), {freed} bytes "
                              f"liberados da SSD", tuple(done), freed, tuple(errors))
