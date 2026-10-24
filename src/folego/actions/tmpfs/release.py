"""Liberar RAM de um tmpfs: copiar para a SSD, verificar, só então apagar.

A ordem é a segurança: toda recusa acontece antes de qualquer escrita; a linha
``staging`` entra no ledger *antes* do primeiro byte (uma queda no meio da cópia
deixa o meio do caminho registrado, nunca um clone órfão); o clone é conferido
contra a origem; e a remoção da origem só acontece depois do fsync do clone. O
estado ``partial`` fica gravado em vez de inferido, e a liberação inacabada é
recuperável por `recover_staging` — com a origem viva o clone redundante é
descartado; sem origem, o clone nunca é apagado por adivinhação.
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
from ...safely import guard, mounts as mount_rules
from ...safely.hashing import sha256_file
from ..disk import planner
from ..disk.measure import measure_tree
from .inventory import TmpfsEntry, entry_at
from .holders import holder_index
from .ledger import (LedgerRecord, MAX_RETAINED_BYTES, RETENTION_DAYS,
                     STATE_DROPPED, STATE_EXPIRED, STATE_PARTIAL, STATE_RELEASED,
                     STATE_RESTORED, STATE_STAGING, UNRESOLVED_STATES)
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
    # contabilidade fina (F2/6b): `bytes` é o lógico (tamanho aparente) e também o
    # transferido pela cópia; `allocated_bytes` é o que o clone ocupa de fato no
    # SSD (st_blocks*512); `ram_observed_bytes` é a variação medida por statvfs.
    # Desconhecido é None — nunca zero por omissão.
    allocated_bytes: int = 0
    ram_observed_bytes: int | None = None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "entry_id": self.entry_id, "reason": self.reason,
                "bytes": self.bytes, "stored": self.stored, "sha256": self.sha256,
                "freed_bytes": self.freed_bytes,
                "allocated_bytes": self.allocated_bytes,
                "ram_observed_bytes": self.ram_observed_bytes}


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


def staging_bytes(ledger, *, measure_fn=None, deadline_s: float = 10.0):
    """(bytes, problemas) dos clones `staging` — a parte não certificada da cota.

    A linha `staging` registra bytes 0 (ainda não certificados) e fica fora do
    orçamento do `expire` (apagar a única cópia seria adivinhação); mas o clone
    existe e ocupa SSD. Contá-lo **aqui** impede que quedas repetidas empilhem
    clones sem que nenhuma nova liberação caiba no teto comum de retenção/staging.
    Clone que não mede por inteiro (prazo, permissão) **não vira zero**: os bytes
    são desconhecidos e o ato que depende da cota recusa com o problema nomeado.
    """
    measure = measure_fn or measure_tree
    total, problems = 0, []
    for record in ledger.records().values():
        if record.state != STATE_STAGING:
            continue
        stored = _registered_path(record.stored)
        if stored is None:
            problems.append(f"staging {record.entry_id}: caminho registrado ilegível")
            continue
        if not stored.exists():
            continue  # sumido do disco: contribui zero porque está ausente, não porque não sei
        stat = measure(stored, deadline_s=deadline_s)
        if stat.truncated or stat.errors:
            problems.append(f"staging {record.entry_id}: {stored} não mediu por inteiro")
            continue
        total += stat.bytes
    return total, problems


def _fresh_entry(path: str, *, volume: str = "", proc_root: str | None = None,
                 now: float | None = None) -> TmpfsEntry:
    """Re-derivado no momento da mutação: o plano pode estar superado."""
    mounts = read_mounts(proc_root)
    holders = holder_index(prefixes=(volume or path,), proc_root=proc_root)
    return entry_at(path, mounts, holders, volume=volume, now=now)


def _refuse(entry_id: str, reason: str) -> ReleaseResult:
    return ReleaseResult(False, entry_id, reason)


def _ledger_refusal(ledger) -> str | None:
    """Ledger ilegível/inconsistente fecha a porta antes de qualquer mutação.

    Agir sobre um ledger com linha que não foi lida seria decidir com mapa
    incompleto — a liberação repetida e o clone órfão da R11/R04. O problema é
    nomeado; o reparo é a edição do arquivo com o app parado.
    """
    problems = ledger.problems()
    if problems:
        return ("refused: ledger inconsistente; nada foi alterado: "
                + "; ".join(problems))
    return None


def _volume_free(statvfs_fn, volume: str) -> int | None:
    """Espaço livre do volume, ou None quando o volume não responde.

    É a medição *observada* do ato, separada do tamanho aparente: num tmpfs,
    páginas presentes e tamanho de conteúdo divergem (buraco não é página), e é a
    variação observada que diz quanto de RAM voltou de verdade. Volume ilegível
    não vira zero — vira `None`, e o resultado nomeia a ausência.
    """
    try:
        vfs = statvfs_fn(str(volume))
    except OSError:
        return None
    return vfs.f_bavail * vfs.f_frsize


def release_item(plan, item, *, ledger, dest_root=None, audit=None, confirm=False,
                 entry_fn=_fresh_entry, statvfs_fn=os.statvfs, mounts_fn=None,
                 now: float | None = None, allowed_roots=None, remove_fn=None,
                 proc_root=None) -> ReleaseResult:
    now = time.time() if now is None else now
    entry_id = _entry_id(now)
    src = Path(item.path)
    if not confirm:
        return _refuse(entry_id, "refused: liberar RAM exige --confirmar; "
                                 "nada foi alterado")

    refusal = _ledger_refusal(ledger)
    if refusal:
        return _refuse(entry_id, refusal)

    held = ledger.find(item.path)
    if held is not None and held.state in UNRESOLVED_STATES:
        if held.state == STATE_STAGING:
            return _refuse(entry_id, f"refused: {item.path} tem liberação inacabada "
                                     f"no ledger como staging ({held.entry_id}); rode "
                                     "folego tmpfs recover antes de liberar de novo")
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

    # R12/F2: XDG sob a home é convenção, não prova — o destino tem de ser
    # comprovadamente não-RAM e não o mesmo monte da origem (copiar para dentro do
    # tmpfs não devolve capacidade a nada). A tabela é lida no ato; os testes
    # injetam a fixture pelo parâmetro.
    table = (mounts_fn or read_mounts)(proc_root)
    dest_mount = mount_rules.destination_verdict(probe, source_mount=item.volume,
                                                 mounts=table)
    if not dest_mount.ok:
        return _refuse(entry_id, f"{dest_mount.reason} — o destino de retenção "
                                 f"é {probe}")

    if dest.exists():
        return _refuse(entry_id, f"refused: {dest} já existe — itens homônimos "
                                 "colidem nesse destino, e o clone já ledgerado "
                                 "seria pisado")

    vfs = statvfs_fn(str(probe))
    livre = vfs.f_bavail * vfs.f_frsize
    necessario = 2 * gate       # o clone + a mesma quantia de reserva do volume
    if livre < necessario:
        return _refuse(entry_id, f"refused: o destino {probe} tem "
                                 f"{planner.fmt_bytes(livre)} livres, menos que os "
                                 f"{planner.fmt_bytes(necessario)} necessários para "
                                 f"copiar {planner.fmt_bytes(gate)} com folga antes "
                                 "de apagar a origem")

    # Cota conjunta (F2/entrega 6): retenção certificada E clones `staging` contam
    # contra o mesmo teto — o clone não certificado ocupa SSD igual, mesmo sem
    # entrar no orçamento do `expire` (lá ele é intocável).
    retido = ledger.retained_bytes()
    em_staging, staging_problems = staging_bytes(ledger)
    if staging_problems:
        return _refuse(entry_id, "refused: cota conjunta não verificável ("
                                 + "; ".join(staging_problems)
                                 + "); nada foi alterado")
    restantes = MAX_RETAINED_BYTES - retido - em_staging
    if gate > restantes:
        oldest = ledger.oldest()
        cand = (f"a candidata a expirar é {oldest.entry_id} ({oldest.src})" if oldest
                else "nada está retido — o item sozinho passa do teto")
        return _refuse(entry_id, f"refused: reter mais {gate} bytes estouraria o "
                                 f"orçamento de {MAX_RETAINED_BYTES} ({retido} "
                                 f"retidos + {em_staging} em staging); {cand}")

    # A linha entra ANTES do primeiro byte: a janela entre a cópia e o registro
    # `partial` era o clone órfão da R11 — queda no meio deixava um destino que
    # nenhuma contagem via. Agora o meio do caminho está escrito (`staging`, bytes
    # 0: ainda não certificados) e o `recover` sabe o que fazer com ele.
    staging_event = _audit(audit, entry_id, STATE_STAGING, [str(src), str(dest)],
                           plan_digest=plan.digest)
    ledger.append(**_fields(entry_id, item, fresh, dest, "", 0, STATE_STAGING,
                            staging_event))

    ram_before = _volume_free(statvfs_fn, item.volume)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, symlinks=True)
        else:
            shutil.copy2(src, dest)
    except OSError as err:
        _quiet_remove(dest)
        _drop_staging(ledger, entry_id, item, fresh, dest, audit,
                      plan_digest=plan.digest,
                      error=f"a cópia falhou: {err.strerror or err}; a origem "
                            "está intacta")
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
        _drop_staging(ledger, entry_id, item, fresh, dest, audit,
                      plan_digest=plan.digest,
                      error=f"o digest não pôde ser lido: {err.strerror or err}")
        return _refuse(entry_id, f"refused: o digest não pôde ser lido "
                                 f"({err.strerror or err}); nada foi apagado")

    if source_digest != clone_digest:
        _quiet_remove(dest)
        _drop_staging(ledger, entry_id, item, fresh, dest, audit,
                      plan_digest=plan.digest,
                      error="o digest do clone difere da origem; o clone foi desfeito")
        return _refuse(entry_id, "refused: o digest do clone difere da origem; "
                                 "nada foi apagado")

    # o clone existe e o original ainda está lá: esse estado é registrado, não inferido
    partial_event = _audit(audit, entry_id, STATE_PARTIAL, [str(src), str(dest)],
                           plan_digest=plan.digest)
    ledger.append(**_fields(entry_id, item, fresh, dest, clone_digest, clone_bytes,
                            STATE_PARTIAL, partial_event))
    clone_allocated = _sync_tree(dest)
    _sync_fd(dest.parent)

    remove = remove_fn or _remove
    try:
        remove(src)
    except OSError as err:
        _audit(audit, entry_id, STATE_PARTIAL, [str(src), str(dest)],
               plan_digest=plan.digest,
               error=f"a origem não pôde ser removida: {err.strerror or err}")
        return ReleaseResult(False, entry_id,
                             f"parcial: o clone está em {dest} e registrado como "
                             f"partial; a origem não foi removida "
                             f"({err.strerror or err}); nada foi perdido",
                             bytes=clone_bytes, stored=str(dest), sha256=clone_digest,
                             freed_bytes=0, allocated_bytes=clone_allocated)

    released_event = _audit(audit, entry_id, STATE_RELEASED, [str(src), str(dest)],
                            plan_digest=plan.digest)
    ledger.append(**_fields(entry_id, item, fresh, dest, clone_digest, clone_bytes,
                            STATE_RELEASED, released_event))
    ram_after = _volume_free(statvfs_fn, item.volume)
    ram_observed = (ram_after - ram_before
                    if ram_before is not None and ram_after is not None else None)
    return ReleaseResult(True, entry_id, "ok", bytes=clone_bytes, stored=str(dest),
                         sha256=clone_digest, freed_bytes=clone_bytes,
                         allocated_bytes=clone_allocated,
                         ram_observed_bytes=ram_observed)


def _sync_fd(path: Path) -> None:
    """fsync de um caminho (arquivo OU diretório): O_RDONLY + fsync funciona nos dois."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_tree(path: Path) -> int:
    """fsync de cada arquivo copiado e soma dos bytes alocados (st_blocks*512).

    O `tree_digest` leu a cópia pela page cache, então "verificado igual" ainda não
    quer dizer "chegou à SSD" — e é logo depois dele que a origem é apagada. O
    fsync do diretório sozinho não fecha essa janela. A soma do alocado aproveita a
    mesma caminhada: é o número que diz o que o clone ocupa de verdade (não o
    tamanho aparente, que num arquivo esparso mente).
    """
    arquivos = [path] if path.is_file() else sorted(path.rglob("*"))
    total = 0
    for p in arquivos:
        if p.is_file():
            _sync_fd(p)
            if not p.is_symlink():
                total += p.stat().st_blocks * 512
    return total


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


def _registered_path(value) -> Path | None:
    """Linha ilegível não vira mutação: caminho registrado tem de ser absoluto.

    O `_hydrate` de uma linha quebrada (versão futura, edição à mão, escrita
    truncada) devolve campos vazios — e ``Path("")`` é ``.``: se o diretório atual
    cair dentro de uma raiz permitida, um `expire`/`recover` apagaria o diretório
    de trabalho. Desconhecido/ilegível nunca autoriza mutação; quem chama trata
    `None` como "nada foi tocado" e relata.
    """
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else None


def _drop_staging(ledger, entry_id, item, fresh, dest, audit, *, plan_digest=None,
                  error=None) -> None:
    """Fecha a linha `staging` de uma tentativa que não virou clone certificado.

    `dropped` é o terminal honesto desta tentativa: a origem está intacta e nenhum
    byte *certificado* ficou na SSD — diferente de `partial`, que diz "clone retido
    e conferível". O evento de auditoria carrega o motivo, para a transição não ser
    um sumiço mudo no diário (§7).
    """
    event = _audit(audit, entry_id, STATE_DROPPED, [item.path, str(dest)],
                   plan_digest=plan_digest, error=error)
    ledger.append(**_fields(entry_id, item, fresh, dest, "", 0, STATE_DROPPED, event))


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

    def to_dict(self) -> dict:
        return {"ok": self.ok, "entry_id": self.entry_id, "reason": self.reason,
                "bytes": self.bytes, "restored_to": self.restored_to}


@dataclass(frozen=True)
class ExpireResult:
    ok: bool
    reason: str
    victims: tuple[str, ...] = ()
    freed_bytes: int = 0
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"ok": self.ok, "reason": self.reason,
                "victims": list(self.victims), "freed_bytes": self.freed_bytes,
                "errors": list(self.errors)}


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
    refusal = _ledger_refusal(ledger)
    if refusal:
        return RestoreResult(False, str(record_or_id), refusal)
    record = record_or_id if isinstance(record_or_id, LedgerRecord) \
        else ledger.find(str(record_or_id))
    if record is None:
        return RestoreResult(False, str(record_or_id), "refused: entrada desconhecida "
                                                       "no ledger")
    if record.state not in (STATE_RELEASED, STATE_PARTIAL):
        if record.state == STATE_STAGING:
            return RestoreResult(False, record.entry_id,
                                 "refused: a entrada está staging (clone não "
                                 "certificado); rode folego tmpfs recover")
        return RestoreResult(False, record.entry_id,
                             f"refused: a entrada está {record.state}")
    entry_id = record.entry_id

    original = _registered_path(record.src)
    stored_path = _registered_path(record.stored)
    if original is None or stored_path is None:
        return RestoreResult(False, entry_id,
                             "refused: a entrada não tem caminhos absolutos "
                             "registrados; nada foi alterado")
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
    refusal = _ledger_refusal(ledger)
    if refusal:
        return ExpireResult(False, refusal)
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
        payload = _registered_path(record.stored)
        if payload is None:
            errors.append(f"{record.entry_id}: o payload registrado não é um caminho "
                          "absoluto; nada foi tocado")
            continue
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


RECOVER_KIND = "tmpfs.recover"


@dataclass(frozen=True)
class RecoverResult:
    ok: bool
    reason: str
    dropped: tuple[str, ...] = ()
    kept: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {"ok": self.ok, "reason": self.reason, "dry_run": self.dry_run,
                "dropped": list(self.dropped), "kept": list(self.kept),
                "notes": list(self.notes), "errors": list(self.errors)}


def recover_staging(*, ledger, audit=None, confirm=False, allowed_roots=None,
                    remove_fn=_remove) -> RecoverResult:
    """Fecha liberações inacabadas (linha `staging`) sem adivinhar conteúdo.

    A origem viva é a âncora: com ela no lugar, o clone inacabado é redundante por
    construção (a cópia só teria terminado antes de a origem sumir), então o clone
    é descartado e a linha fecha como `dropped` — o caminho volta a ser liberável.
    Origem sumida é o caso oposto: o clone não certificado pode ser a única cópia
    restante; apagá-lo seria adivinhação destrutiva. Nada é tocado, a entrada fica
    `staging` e a decisão manual é nomeada no resultado.
    """
    refusal = _ledger_refusal(ledger)
    if refusal:
        return RecoverResult(False, refusal)
    staging = sorted((r for r in ledger.records().values()
                      if r.state == STATE_STAGING),
                     key=lambda r: (r.ts, r.entry_id))
    if not staging:
        return RecoverResult(True, "nada a recuperar: nenhuma liberação inacabada")
    roots = list(allowed_roots) if allowed_roots else default_allowed_roots()

    def origin_alive(record) -> bool:
        src = _registered_path(record.src)
        return src is not None and src.exists()

    if not confirm:
        # dry-run classifica pelo que é verificável sem mutar: existência da origem.
        # Guard e falhas de remoção só aparecem no ato confirmado — o texto diz
        # "seriam", não "serão"; quem confirma recebe o relatório real.
        discardable = [r for r in staging if origin_alive(r)]
        kept = [r for r in staging if not origin_alive(r)]
        return RecoverResult(
            True,
            f"dry-run: {len(discardable)} clone(s) inacabado(s) seriam descartado(s) "
            f"e {len(kept)} mantido(s) para decisão manual; nada foi alterado",
            dropped=tuple(r.entry_id for r in discardable),
            kept=tuple(r.entry_id for r in kept),
            dry_run=True)

    dropped, kept, notes, errors = [], [], [], []
    for record in staging:
        src = _registered_path(record.src)
        if src is None:
            kept.append(record.entry_id)
            notes.append(f"{record.entry_id}: o registro não tem origem absoluta; "
                         "nada foi tocado — decisão manual")
            continue
        if not src.exists():
            kept.append(record.entry_id)
            notes.append(f"{record.entry_id}: a origem {record.src} sumiu; o clone "
                         f"{record.stored} não foi tocado — pode ser a única cópia "
                         "restante (não certificada); decisão manual")
            continue
        payload = _registered_path(record.stored)
        if payload is None:
            errors.append(f"{record.entry_id}: o clone registrado não é um caminho "
                          "absoluto; nada foi tocado")
            continue
        verdict = guard.validate_target(payload, roots)
        if not verdict.ok:
            errors.append(f"{record.entry_id}: {verdict.reason}")
            continue
        try:
            if payload.exists():
                remove_fn(payload)
        except OSError as err:
            errors.append(f"{record.entry_id}: a limpeza do clone falhou "
                          f"({err.strerror or err})")
            continue
        event_id = _audit(audit, record.entry_id, STATE_DROPPED,
                          [record.src, record.stored], kind=RECOVER_KIND,
                          error="liberação inacabada descartada; a origem está intacta")
        _transition(ledger, record, STATE_DROPPED, RECOVER_KIND, event_id)
        dropped.append(record.entry_id)

    return RecoverResult(
        not errors,
        f"recuperação: {len(dropped)} clone(s) inacabado(s) descartado(s), "
        f"{len(kept)} mantido(s) para decisão manual",
        tuple(dropped), tuple(kept), tuple(notes), tuple(errors))
