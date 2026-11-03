"""A promessa deste arquivo é tirar bytes da RAM sem perder nenhum.

Cross-device é o ponto, não um bug: o `Quarantine.move_in` do M5 recusa rename
entre dispositivos porque lá a promessa é zero-copy; aqui a promessa é liberar
memória, então o movimento é explicitamente copy → verify → unlink, e o ledger
registra o meio do caminho.
"""
import os
import json
import shutil
import time
from dataclasses import replace
from pathlib import Path

import pytest

from folego.actions.tmpfs import release
from folego.actions.tmpfs.inventory import TmpfsEntry
from folego.actions.tmpfs.ledger import (MAX_RETAINED_BYTES, STATE_DROPPED, STATE_PARTIAL,
                                          STATE_RELEASED, STATE_RESTORED,
                                          STATE_STAGING, Ledger)
from folego.actions.tmpfs.plan import build_plan
from folego.actions.tmpfs.policy import Policy
from folego.core.tmpfs import TmpfsVolume
from folego.safely.audit import AuditLog

DAY = 86_400
NOW = 1_700_000_000.0
GIB = 1024 ** 3
VOL = TmpfsVolume("/tmp", "tmpfs", 8 * GIB, 2 * GIB, 6 * GIB)


def sandbox_policy(tmp_path):
    """A allow-list do chão falso: o que está sob `tmp_path` é reconhecido.

    Sem isto, a elegibilidade destes testes dependeria do nome que o pytest dá ao
    `tmp_path` dele (ele costuma cair sob `/tmp/pytest-of-*`, que casa com um
    padrão default por acaso) — e `--basetemp` trocaria o resultado.
    """
    return Policy(allow_patterns=(str(tmp_path / "qoder-cli-1000"),
                                  str(tmp_path / "qoder-cli-1000" / "*")))


def item(tmp_path, name="qoder-cli-1000", size=4096, *, under=None, allow=None,
         policy=None):
    """Um diretório real na SSD-emulada do tmp_path, velho e sem dono aberto.

    O blob é **esparso** (`touch` + `truncate`): estes testes precisam de um item de
    1 GiB aparente para a checagem de folga, e `write_bytes(b"a" * 1GiB)` alocaria
    isso de verdade — em `/tmp`, que neste host é tmpfs de 7,3 G e já viu ENOSPC.
    `under`/`allow` existem para o caso dos homônimos: um segundo item com o mesmo
    nome, em outro pai, com a própria allow-list. `policy` existe para o caso do
    portão de orçamento: abrir `max_item_bytes` é o que torna aquele ramo vivo.
    """
    src = (Path(under) if under is not None else tmp_path) / name
    src.mkdir(parents=True, exist_ok=True)
    blob = src / "blob.bin"
    blob.touch()
    os.truncate(str(blob), size)
    old = NOW - 10 * DAY
    os.utime(src / "blob.bin", (old, old))
    os.utime(src, (old, old))
    entry = TmpfsEntry(path=str(src), name=src.name, volume="/tmp", kind="dir",
                       uid=os.getuid(), bytes=size, files=1, age_days=10.0,
                       is_mount_point=False, under_mount=False, holder_pids=())
    if policy is None:
        policy = (Policy(allow_patterns=tuple(allow)) if allow
                  else sandbox_policy(tmp_path))
    plan = build_plan((VOL,), (entry,), policy, now=NOW)
    return plan, plan.find(str(src)), src


def free(**over):
    """entry_fn padrão: re-derivado limpo, sem holder, sem monte.

    `over` corrige campos por teste (ex.: `bytes=1 * GIB`) para que o re-derivado e o
    item do plano tenham o mesmo tamanho — senão a checagem de folga compararia um
    número que não é o de nenhum dos dois. Os defaults entram por `update`, não por
    `**over` na chamada: `bytes=` e `holder_pids=` já são literais ali, e Python
    recusa o argumento duplicado antes de qualquer asserção.
    """
    def entry_fn(p, **kw):
        campos = dict(name=Path(p).name, volume="/tmp", kind="dir", uid=os.getuid(),
                      bytes=4096, files=1, age_days=10.0, is_mount_point=False,
                      under_mount=False, holder_pids=())
        campos.update(over)
        return TmpfsEntry(path=p, **campos)
    return entry_fn


def roots(tmp_path):
    return [tmp_path, Path.home() / ".local"]


@pytest.fixture
def book(tmp_path):
    return Ledger(tmp_path / "ledger.jsonl")


@pytest.fixture
def audit(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


def test_release_without_confirmation_writes_nothing(tmp_path, book, audit):
    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, audit=audit,
                               dest_root=tmp_path / "retida",
                               allowed_roots=roots(tmp_path))
    assert res.ok is False and "--confirmar" in res.reason
    assert (src / "blob.bin").exists()
    assert not (tmp_path / "retida").exists()
    assert book.retained_count() == 0


def test_release_copies_verifies_and_frees_the_bytes(tmp_path, book, audit):
    plan, it, src = item(tmp_path, size=8192)
    res = release.release_item(plan, it, ledger=book, audit=audit, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is True and res.freed_bytes == 8192
    assert not src.exists(), "a origem tem de sumir — é RAM liberada"
    stored = Path(res.stored)
    # o fixture é esparso: o conteúdo copiado é zero, e é isso que tem de chegar igual
    assert (stored / "blob.bin").read_bytes() == b"\0" * 8192
    assert book.records()[res.entry_id].state == STATE_RELEASED
    assert book.retained_bytes() == 8192
    kinds = [r["kind"] for r in audit.tail(8)]
    assert "tmpfs.release" in kinds


def test_a_holder_that_appeared_after_the_plan_refuses_the_release(tmp_path, book):
    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida",
                               entry_fn=free(holder_pids=(4242,)),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "fd aberto" in res.reason
    assert res.reason.count("refused:") == 1, "o reason do classify já traz o prefixo"
    assert (src / "blob.bin").exists()


def test_a_mount_point_that_appeared_after_the_plan_refuses(tmp_path, book):
    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida",
                               entry_fn=free(is_mount_point=True),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "montagem" in res.reason
    assert res.reason.count("refused:") == 1
    assert (src / "blob.bin").exists()


def test_release_refuses_when_the_destination_has_no_room(tmp_path, book):
    plan, it, src = item(tmp_path, size=1 * GIB)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida",
                               entry_fn=free(bytes=1 * GIB),
                               statvfs_fn=lambda p: _vfs(1 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "destino" in res.reason
    assert (src / "blob.bin").exists()


def test_release_refuses_when_retention_would_exceed_the_budget(tmp_path, book):
    plan, it, src = item(tmp_path, size=1024)
    book.append(entry_id="velha", src="/tmp/velha", volume="/tmp",
                stored=str(tmp_path / "velha"), bytes=MAX_RETAINED_BYTES,
                sha256="x", age_days=1.0, matched_pattern="/tmp/tmp*",
                holder_pids=(), state=STATE_RELEASED, action_id="tmpfs.release",
                audit_event_id="e")
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "orçamento" in res.reason
    assert "velha" in res.reason, "a recusa tem de apontar a candidata a expire"


def test_an_item_bigger_than_the_ceiling_refuses_without_a_candidate(tmp_path, book):
    """O outro lado do portão de orçamento: `oldest()` devolve `None` e ainda recusa.

    A recusa com candidata existe acima; esta cobre o ledger vazio — o lugar onde a
    versão antiga lia `oldest.entry_id` às cegas e estourava `AttributeError` no
    caminho da recusa. Com a `max_item_bytes` default (2 GiB) o caminho é
    inalcançável: 2 GiB nunca passam dos 3 GiB de orçamento livre. A política aqui
    abre o teto por item de propósito, porque é assim que o portão fica vivo para
    quem configurar a política — e é isso que o teste pinar, não a default.
    """
    policy = Policy(allow_patterns=sandbox_policy(tmp_path).allow_patterns,
                    max_item_bytes=6 * GIB)
    plan, it, src = item(tmp_path, size=4096, policy=policy)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida",
                               entry_fn=free(bytes=4 * GIB),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "orçamento" in res.reason
    assert "nada está retido" in res.reason, "sem candidata, a recusa diz o porquê"
    assert res.reason.count("refused:") == 1
    assert (src / "blob.bin").exists()
    assert not (tmp_path / "retida").exists(), "nada foi copiado"
    assert book.retained_count() == 0


def test_release_refuses_a_ram_destination(tmp_path, book):
    """Entrega 6: retenção em tmpfs não libera a origem — XDG não é prova de SSD.

    A tabela de montes é fixture: o destino cai num `tmpfs`; nada é copiado e a
    recusa nomeia o tipo do monte. Sem esta verificação, `paths` sob a home
    valeria por convenção, não por prova.
    """
    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               mounts_fn=lambda proc_root=None: (
                                   (str(tmp_path), "tmpfs"), ("/", "ext4")),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "RAM" in res.reason
    assert (src / "blob.bin").exists()
    assert book.retained_count() == 0, "recusa antes de qualquer linha do ledger"
    assert not (tmp_path / "retida").exists(), "nada foi copiado"


def test_release_refuses_a_destination_on_the_source_mount(tmp_path, book):
    """Copiar para dentro do mesmo tmpfs não devolve capacidade a nada."""
    plan, it, src = item(tmp_path)
    mesmo_monte = replace(it, volume=str(tmp_path))
    res = release.release_item(plan, mesmo_monte, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               mounts_fn=lambda proc_root=None: (
                                   (str(tmp_path), "ext4"),),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "mesmo monte" in res.reason
    assert (src / "blob.bin").exists()


def test_release_refuses_a_destination_outside_known_mounts(tmp_path, book):
    """Host ilegível não é permissão: sem a tabela, o destino não tem prova."""
    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               mounts_fn=lambda proc_root=None: (),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "conhecido" in res.reason
    assert (src / "blob.bin").exists()


def test_staging_clones_count_in_the_joint_ceiling(tmp_path, book):
    """Cota conjunta (entrega 6): clone não certificado ocupa SSD e conta no teto.

    A linha `staging` registra bytes 0 e fica fora do orçamento do `expire` (lá
    ela é intocável); mas enquanto existe, ocupa disco. A cota do próximo
    release soma o que os clones em staging medem agora.
    """
    clone = tmp_path / "staging-clone"
    clone.mkdir()
    meio = clone / "meio.bin"
    meio.touch()
    os.truncate(str(meio), MAX_RETAINED_BYTES - 1024)  # esparso: só st_size
    book.append(entry_id="st-1", src=str(tmp_path / "origem"), volume="/tmp",
                stored=str(clone), bytes=0, sha256="", age_days=0.0,
                matched_pattern=None, holder_pids=(), state=STATE_STAGING,
                action_id="tmpfs.release")

    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               mounts_fn=lambda proc_root=None: (("/", "ext4"),),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)

    assert res.ok is False and "orçamento" in res.reason
    assert "staging" in res.reason, "a recusa nomeia a parte não certificada"
    assert (src / "blob.bin").exists() and not (tmp_path / "retida").exists()


def test_staging_bytes_measures_only_living_staging_clones(tmp_path, book):
    clone = tmp_path / "clone"
    (clone / "sub").mkdir(parents=True)
    (clone / "sub" / "b.bin").write_bytes(b"a" * 100)
    book.append(entry_id="st-vivo", src=str(tmp_path / "a"), volume="/tmp",
                stored=str(clone), bytes=0, sha256="", age_days=0.0,
                matched_pattern=None, holder_pids=(), state=STATE_STAGING,
                action_id="tmpfs.release")
    book.append(entry_id="st-sumido", src=str(tmp_path / "b"), volume="/tmp",
                stored=str(tmp_path / "sumiu"), bytes=0, sha256="", age_days=0.0,
                matched_pattern=None, holder_pids=(), state=STATE_STAGING,
                action_id="tmpfs.release")
    book.append(entry_id="certificada", src=str(tmp_path / "c"), volume="/tmp",
                stored=str(clone), bytes=100, sha256="x", age_days=0.0,
                matched_pattern=None, holder_pids=(), state=STATE_RELEASED,
                action_id="tmpfs.release")

    assert release.staging_bytes(book) == (100, []), \
        "só staging existente conta; certificado fica no retained_bytes"


def test_an_unmeasurable_staging_clone_refuses_the_joint_ceiling(tmp_path, book):
    """Desconhecido não é zero: clone ilegível fecha a cota em vez de sumir dela."""
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "b.bin").write_bytes(b"a" * 100)
    book.append(entry_id="st-escuro", src=str(tmp_path / "a"), volume="/tmp",
                stored=str(clone), bytes=0, sha256="", age_days=0.0,
                matched_pattern=None, holder_pids=(), state=STATE_STAGING,
                action_id="tmpfs.release")
    os.chmod(clone, 0o000)
    try:
        assert release.staging_bytes(book)[1], "clone ilegível é problema relatado"

        plan, it, src = item(tmp_path)
        res = release.release_item(plan, it, ledger=book, confirm=True,
                                   dest_root=tmp_path / "retida", entry_fn=free(),
                                   mounts_fn=lambda proc_root=None: (("/", "ext4"),),
                                   statvfs_fn=lambda p: _vfs(20 * GIB),
                                   allowed_roots=roots(tmp_path), now=NOW)
        assert res.ok is False and "não verificável" in res.reason
        assert res.reason.count("refused:") == 1
        assert (src / "blob.bin").exists() and not (tmp_path / "retida").exists()
    finally:
        os.chmod(clone, 0o700)


def test_release_reports_allocated_and_observed_bytes(tmp_path, book):
    """Contabilidade fina (6b): lógico, alocado e observado são medidas separadas."""
    plan, it, src = item(tmp_path)
    livres = [10 * GIB, 10 * GIB + 8192]  # o volume, antes e depois do ato

    def vfs_fn(p):
        if p == it.volume:
            return _vfs(livres.pop(0))
        return _vfs(20 * GIB)

    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               mounts_fn=lambda proc_root=None: (("/", "ext4"),),
                               statvfs_fn=vfs_fn, allowed_roots=roots(tmp_path),
                               now=NOW)

    assert res.ok is True
    assert res.bytes == 4096, "lógico segue sendo o tamanho aparente"
    esperado = sum(p.stat().st_blocks * 512
                   for p in (tmp_path / "retida").rglob("*")
                   if p.is_file() and not p.is_symlink())
    assert res.allocated_bytes == esperado, "alocado é medido no clone, não estimado"
    assert res.ram_observed_bytes == 8192, "observado é a variação do statvfs"


def test_release_reports_no_observation_when_the_volume_is_unreadable(tmp_path, book):
    """Desconhecido ≠ zero: volume ilegível não vira 'nada foi liberado'."""
    plan, it, src = item(tmp_path)

    def vfs_fn(p):
        if p == it.volume:
            raise OSError(5, "I/O error")
        return _vfs(20 * GIB)

    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               mounts_fn=lambda proc_root=None: (("/", "ext4"),),
                               statvfs_fn=vfs_fn, allowed_roots=roots(tmp_path),
                               now=NOW)

    assert res.ok is True
    assert res.ram_observed_bytes is None, "sem observação, nada de zero inventado"
    esperado = sum(p.stat().st_blocks * 512
                   for p in (tmp_path / "retida").rglob("*")
                   if p.is_file() and not p.is_symlink())
    assert res.allocated_bytes == esperado


def test_dev_shm_is_measured_never_mutated(tmp_path, book):
    """R9: o guard já blacklista /dev; este teste prova que não afrouxamos nada.

    A allow-list é alargada de propósito aqui: sem um padrão casando, a recusa viria
    do filtro de padrão e o teste não diria nada sobre o guard. Nada é criado sob
    `tmp_path` — o item apontado não existe, e é exatamente por isso que a recusa tem
    de vir antes de qualquer escrita.
    """
    assert "/dev/shm" not in release.MUTABLE_VOLUMES
    entry = TmpfsEntry(path="/dev/shm/bloco", name="bloco", volume="/dev/shm",
                       kind="dir", uid=os.getuid(), bytes=1, files=1, age_days=9.0,
                       is_mount_point=False, under_mount=False, holder_pids=())
    plan = build_plan((TmpfsVolume("/dev/shm", "tmpfs", 8 * GIB, 0, 8 * GIB),),
                      (entry,), Policy(allow_patterns=("/dev/shm/*",)), now=NOW)
    res = release.release_item(plan, plan.find("/dev/shm/bloco"), ledger=book,
                               confirm=True, dest_root=tmp_path / "retida",
                               entry_fn=free(),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "blacklisted prefix" in res.reason
    assert not (tmp_path / "retida").exists()
    assert book.retained_count() == 0


def test_a_failed_removal_leaves_the_clone_recorded_as_partial(tmp_path, book, audit):
    plan, it, src = item(tmp_path)

    def boom(path):
        raise OSError(30, "Read-only file system")

    res = release.release_item(plan, it, ledger=book, audit=audit, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW, remove_fn=boom)
    assert res.ok is False
    assert (src / "blob.bin").exists(), "nada se perde: o original continua lá"
    assert Path(res.stored).exists(), "o clone existe e está registrado"
    record = book.records()[res.entry_id]
    assert record.state == STATE_PARTIAL
    assert book.retained_bytes() == record.bytes


def test_a_digest_mismatch_refuses_and_keeps_the_original(tmp_path, book, monkeypatch):
    plan, it, src = item(tmp_path)

    def diverged(path):
        # o clone (sob "retida") aparenta outro conteúdo que não a origem
        return ("b" * 64, 4096) if "retida" in str(path) else ("a" * 64, 4096)

    monkeypatch.setattr(release, "tree_digest", diverged)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "digest" in res.reason
    assert (src / "blob.bin").exists()
    assert not any((tmp_path / "retida").rglob("blob.bin")), "o clone divergente é desfeito"
    assert book.find(str(src)).state == STATE_DROPPED, \
        "a tentativa fecha como dropped: nada de staging pendurado"


def test_releasing_a_path_already_in_the_ledger_is_refused(tmp_path, book):
    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok
    again = release.release_item(plan, it, ledger=book, confirm=True,
                                 dest_root=tmp_path / "retida", entry_fn=free(),
                                 statvfs_fn=lambda p: _vfs(20 * GIB),
                                 allowed_roots=roots(tmp_path), now=NOW)
    assert again.ok is False and "ledger" in again.reason


def test_an_item_already_restored_can_be_released_again(tmp_path, book):
    """O ledger não é uma lista de proibidos: `restored` liberou a pena.

    Sem esta distinção, um item devolvido ao tmpfs ficava para sempre marcado no
    ledger e a segunda liberação seria recusada para sempre — o oposto do que o
    `restore` da T10 existe para fazer.
    """
    plan, it, src = item(tmp_path)
    book.append(entry_id="velho", src=it.path, volume="/tmp",
                stored=str(tmp_path / "velho"), bytes=4096, sha256="x",
                age_days=9.0, matched_pattern="/tmp/qoder-cli-1000", holder_pids=(),
                state=STATE_RESTORED, action_id="tmpfs.release", audit_event_id="e")
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is True
    assert book.records()["velho"].state == STATE_RESTORED


def test_two_homonyms_in_the_same_second_do_not_collide(tmp_path, book, audit):
    """Mesmo nome, mesmo segundo → o destino já existe: recusa, não overwrite.

    O `_sanitize(src.name)` no caminho de retenção é o que torna dois itens homônimos
    indistinguíveis. Apagar por cima do clone já ledgerado da liberação anterior
    perderia bytes sem registro; a recusa mantém os dois vivos.
    """
    plan, it, src = item(tmp_path)
    first = release.release_item(plan, it, ledger=book, audit=audit, confirm=True,
                                 dest_root=tmp_path / "retida", entry_fn=free(),
                                 statvfs_fn=lambda p: _vfs(20 * GIB),
                                 allowed_roots=roots(tmp_path), now=NOW)
    assert first.ok
    clone = Path(first.stored)

    other_plan, other_it, other = item(tmp_path, under=tmp_path / "sessoes",
                                        allow=[str(tmp_path / "sessoes"
                                                   / "qoder-cli-1000")])
    again = release.release_item(other_plan, other_it, ledger=book, audit=audit,
                                 confirm=True, dest_root=tmp_path / "retida",
                                 entry_fn=free(),
                                 statvfs_fn=lambda p: _vfs(20 * GIB),
                                 allowed_roots=roots(tmp_path), now=NOW)
    assert again.ok is False and "colide" in again.reason
    assert (clone / "blob.bin").read_bytes() == b"\0" * 4096, "o clone anterior vive"
    assert (other / "blob.bin").exists(), "o homônimo fica onde está"


def test_the_ledger_line_points_at_its_own_audit_event(tmp_path, book, audit):
    """§7: cada transição tem um evento, e a linha do ledger nomeia o dela.

    É o join que permite ao viewer (T13) abrir o evento de um item retido sem
    adivinhar por timestamp.
    """
    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, audit=audit, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    record = book.records()[res.entry_id]
    events = {e["event_id"]: e for e in audit.tail(8)}
    assert record.audit_event_id != ""
    assert record.audit_event_id in events
    assert events[record.audit_event_id]["outcome"] == STATE_RELEASED
    assert events[record.audit_event_id]["targets"] == [str(src), record.stored]


def test_a_destination_that_does_not_exist_yet_is_still_gravable(tmp_path, book):
    """Primeira liberação da vida: o diretório de retenção ainda não existe.

    Validar o gravável no próprio destino (ou no diretório de timestamp, que é o
    primeiro nível do caminho) recusaria para sempre enquanto alguém não criasse a
    árvore — e quem cria a árvore é exatamente esta chamada.
    """
    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "nova" / "retida", entry_fn=free(),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is True, res.reason
    assert (tmp_path / "nova" / "retida").is_dir()


def test_releasing_a_loose_file_verifies_the_bytes_it_clones(tmp_path, book):
    """§6.5 num item que é ARQUIVO, não árvore — e `/tmp/tmp*` é `mktemp` da vida real.

    `rglob("*")` não desce num arquivo: sem o ramo de arquivo, as duas pontas dão o
    SHA-256 do vazio, a verificação vira tautologia, o clone é apagado sem conferido,
    e o ledger grava `bytes: 0` — o teto de 3 GiB deixa de contar qualquer liberação
    de arquivo. Este teste é a única execução do ramo `shutil.copy2`.
    """
    src = tmp_path / "solto.bin"
    src.write_bytes(b"z" * 5000)
    old = NOW - 10 * DAY
    os.utime(src, (old, old))
    entry = TmpfsEntry(path=str(src), name=src.name, volume="/tmp", kind="file",
                       uid=os.getuid(), bytes=5000, files=1, age_days=10.0,
                       is_mount_point=False, under_mount=False, holder_pids=())
    plan = build_plan((VOL,), (entry,), Policy(allow_patterns=(str(src),)), now=NOW)
    res = release.release_item(plan, plan.find(str(src)), ledger=book, confirm=True,
                               dest_root=tmp_path / "retida",
                               entry_fn=free(kind="file"),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is True and res.freed_bytes == 5000
    assert not src.exists()
    assert Path(res.stored).read_bytes() == b"z" * 5000
    assert book.retained_bytes() == 5000, "o ledger não pode contar 0"
    # o SHA do vazio: se o digest não olhou o arquivo, é exatamente este
    assert res.sha256 != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_a_digest_that_cannot_be_read_leaves_no_orphan_clone(tmp_path, book, monkeypatch):
    """A origem pode sumir entre a cópia e o digest; o clone órfão não pode ficar.

    Clone sem linha de ledger é byte retido invisível: nem `retained_bytes()` nem a
    T13 nunca vão contá-lo. O `try` em torno do par de digests é o que fecha isso.
    """
    plan, it, src = item(tmp_path)

    def cega(path):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(release, "tree_digest", cega)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "digest" in res.reason
    assert (src / "blob.bin").exists()
    assert not any((tmp_path / "retida").rglob("blob.bin")), "nenhum clone órfão"
    assert book.retained_count() == 0
    assert book.find(str(src)).state == STATE_DROPPED, \
        "a tentativa fechou como dropped; não sobra staging para o recover"


def test_tree_digest_is_stable_and_order_independent(tmp_path):
    a = tmp_path / "a"
    (a / "sub").mkdir(parents=True)
    (a / "sub" / "b.txt").write_text("conteúdo")
    (a / "a.txt").write_text("abc")
    first, size = release.tree_digest(a)
    os.utime(a / "a.txt", (NOW, NOW))  # mtime não entra no digest
    second, _ = release.tree_digest(a)
    assert first == second and len(first) == 64
    # bytes, não caracteres: "conteúdo" tem 9 bytes em UTF-8 e 8 caracteres
    assert size == len("abc".encode()) + len("conteúdo".encode())


class _vfs:
    def __init__(self, avail):
        self.f_frsize = 4096
        self.f_bavail = avail // 4096


# Devolver e expirar: os dois lados do ledger, com a mesma recusa primeiro.
#
# Restaurar volta a copiar (SSD → tmpfs é outro cross-device) e só apaga o clone
# depois do digest bater. Expirar é o único ato irreversível daqui, e por isso pede
# duas flags.
#
# Comentário e não docstring: este bloco é *acrescentado* a um arquivo que já tem a
# sua docstring de módulo no topo. Uma string solta no meio do arquivo é uma
# expressão que não declara nada — some do `__doc__` e fica mudando o AST à toa.


def stored(tmp_path, book, *, name="sessao-velha", size=4096, days=1.0, entry_id=None,
           bytes=None):
    """Coloca um item no ledger do jeito que release_item o deixaria.

    `bytes` corrige o que o ledger registra, sem mudar o que está no disco: é o
    gancho dos testes que precisam de um registro grande (folga insuficiente,
    excesso de orçamento) sem escrever gigabytes em `tmp_path`.
    """
    payload = tmp_path / "retida" / "20261015T000000Z" / name
    payload.mkdir(parents=True)
    (payload / "blob.bin").write_bytes(b"a" * size)
    digest, total = release.tree_digest(payload)
    entry_id = entry_id or f"1700-{name}"
    # ts explícito: sem ele o "hoje" do relógio real deixaria a idade injetada sem efeito
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - days * DAY))
    book.append(ts=ts, entry_id=entry_id, src=str(tmp_path / name), volume="/tmp",
                stored=str(payload), bytes=total if bytes is None else bytes,
                sha256=digest, age_days=days, matched_pattern="/tmp/tmp*",
                holder_pids=(), state=STATE_RELEASED,
                action_id="tmpfs.release", audit_event_id="e")
    return entry_id, payload


def test_restore_without_confirmation_moves_nothing(tmp_path, book):
    entry_id, payload = stored(tmp_path, book)
    res = release.restore_item(entry_id, ledger=book, allowed_roots=[tmp_path])
    assert res.ok is False and "--confirmar" in res.reason
    assert payload.exists()


def test_the_confirm_gate_precedes_the_id_lookup_in_restore(tmp_path, book):
    """Sem a flag, a única recusa que o `restore` pode devolver é a de confirmação.

    É o contrato que o exit code 2 da CLI vende. `release_item` já tinha a confirmação
    em primeiro lugar (`release.py:107-109`); o `restore_item` olhava o ledger antes, e
    isso fazia a mensagem discordar do código.
    """
    res = release.restore_item("id-que-nao-existe", ledger=book,
                               allowed_roots=[tmp_path])
    assert res.ok is False
    assert "--confirmar" in res.reason and "desconhecida" not in res.reason, res.reason


def test_restore_copies_back_and_frees_the_budget(tmp_path, book, audit):
    entry_id, payload = stored(tmp_path, book, size=8192)
    original = Path(book.records()[entry_id].src)
    res = release.restore_item(entry_id, ledger=book, audit=audit, confirm=True,
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               mounts_fn=lambda: (),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is True
    assert (original / "blob.bin").read_bytes() == b"a" * 8192
    assert not payload.exists(), "devolvido: o clone não pode ficar dos dois lados"
    assert book.records()[entry_id].state == "restored"
    assert book.retained_bytes() == 0


def test_a_digest_mismatch_on_the_way_back_keeps_the_clone(tmp_path, book, monkeypatch):
    """A verificação da volta é o que impede o `restore` de apagar a única cópia boa.

    Sem o par de digests, `restore_item` apagaria o clone da SSD assim que a cópia
    de volta terminasse — e se ela veio truncada, o item se perde nos dois lados.
    A segunda leitura é a árvore que acabou de chegar à RAM: corrompê-la aqui é
    exatamente o caso.
    """
    entry_id, payload = stored(tmp_path, book, size=8192)
    verdadeiro = release.tree_digest
    lidas = []

    def duas_pontas(p):
        digest, total = verdadeiro(p)
        lidas.append(str(p))
        return ("f" * 64 if len(lidas) == 2 else digest), total

    monkeypatch.setattr(release, "tree_digest", duas_pontas)
    res = release.restore_item(entry_id, ledger=book, confirm=True,
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               mounts_fn=lambda: (),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is False and "digest" in res.reason
    assert payload.exists(), "o clone da SSD é a única cópia que restou, e ficou"
    assert not (tmp_path / "sessao-velha").exists(), "a volta truncada foi desfeita"
    assert book.records()[entry_id].state == STATE_RELEASED


def test_restore_refuses_when_the_original_path_already_exists(tmp_path, book):
    entry_id, payload = stored(tmp_path, book)
    Path(book.records()[entry_id].src).mkdir(parents=True)
    res = release.restore_item(entry_id, ledger=book, confirm=True,
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               mounts_fn=lambda: (),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is False and "já existe" in res.reason
    assert payload.exists(), "nada é sobrescrito"


def test_restore_refuses_when_a_mount_appeared_in_the_way(tmp_path, book):
    """R1 vale nas duas direções: devolver para dentro de um monte é recusado."""
    entry_id, payload = stored(tmp_path, book)
    mounted = f"{tmp_path}/sessao-velha/novo-monte"
    res = release.restore_item(entry_id, ledger=book, confirm=True,
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               mounts_fn=lambda: ((mounted, "fuse.portal"),),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is False and "monte" in res.reason
    assert payload.exists(), "o retido continua na SSD"


def test_restore_refuses_when_the_volume_has_no_room(tmp_path, book):
    # bytes= e não size=: o payload real fica em 4096, o registro diz 6 GiB
    entry_id, payload = stored(tmp_path, book, bytes=6 * GIB)
    res = release.restore_item(entry_id, ledger=book, confirm=True,
                               statvfs_fn=lambda p: _vfs(1 * GIB),
                               mounts_fn=lambda: (),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is False and "espaço" in res.reason


def test_restore_refuses_when_the_destination_sits_under_a_foreign_mount(tmp_path, book):
    """A outra direção de `_foreign_mount`: o monte que *contém* o destino não é o volume.

    `test_restore_refuses_when_a_mount_appeared_in_the_way` exerce `m.startswith(path)`
    — o monte que nasceu *dentro* do destino. Este exerce o `deepest != volume`: é ele
    que recusa devolver para dentro de um `private/tmp` montado por cima do caminho.
    Sem este teste, apagar o ramo do `covering` deixa a suíte inteira verde.
    """
    entry_id, payload = stored(tmp_path, book)
    inside = str(Path(book.records()[entry_id].src).parent.resolve())
    res = release.restore_item(entry_id, ledger=book, confirm=True,
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               mounts_fn=lambda: ((inside, "ext4"),),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is False and "monte" in res.reason
    assert payload.exists(), "o retido continua na SSD"
    assert not (tmp_path / "sessao-velha").exists()


def test_restore_works_from_a_partial_record_whose_original_evaporated(tmp_path, book,
                                                                       audit):
    """`partial` + reboot: o clone na SSD passa a ser a única cópia que existe.

    A liberação registra `partial` quando o `unlink` da origem falha. Se o tmpfs foi
    esvaziado antes de o usuário pedir a volta, `restore` é a única saída — por isso a
    guarda aceita os dois estados. Reduzi-la a `released` não descarta um caso teórico:
    descarta o dado de quem teve a remoção recusada.
    """
    entry_id, payload = stored(tmp_path, book, size=8192)
    record = book.records()[entry_id]
    book.append(**{**record.to_dict(), "state": STATE_PARTIAL})
    original = Path(record.src)
    assert not original.exists()
    res = release.restore_item(entry_id, ledger=book, audit=audit, confirm=True,
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               mounts_fn=lambda: (),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is True
    assert (original / "blob.bin").read_bytes() == b"a" * 8192
    assert book.records()[entry_id].state == "restored"
    assert book.retained_bytes() == 0


def test_a_restore_refuses_when_the_retained_payload_rotted_on_the_ssd(tmp_path, book):
    """O `sha256` do ledger é a certidão do retido, e tem de ser lido antes de copiar.

    Se o digest do clone fosse calculado só *depois* da cópia de volta, os dois lados
    divergiriam juntos — payload podre na SSD, destino podre na RAM, digest batendo —
    e o `restore` diria "ok" enquanto entregava corrupto. Aí o campo `sha256` do §7 é
    decoração. A conferência acontece antes de qualquer byte escrito no volume.
    """
    entry_id, payload = stored(tmp_path, book, size=8192)
    (payload / "blob.bin").write_bytes(b"b" * 8192)
    res = release.restore_item(entry_id, ledger=book, confirm=True,
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               mounts_fn=lambda: (),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is False and "digest" in res.reason
    assert payload.exists(), "o que apodreceu fica onde está, para inspeção"
    assert not (tmp_path / "sessao-velha").exists(), "nada foi escrito no volume"
    assert book.records()[entry_id].state == STATE_RELEASED


def test_a_copytree_failure_on_the_way_back_leaves_no_half_restored_tree(tmp_path, book,
                                                                         monkeypatch):
    """A volta tem o mesmo hazard da liberação: metade na RAM, tudo na SSD, "já existe" eterno.

    `copytree` não propaga o primeiro erro — ele ajunta os por-arquivo num
    `shutil.Error`, que **herda de `OSError`** (conferido no `.venv`: `__mro__ =
    [Error, OSError, Exception, …]`), então o `except OSError` da volta pega o
    agregado e desfaz a árvore parcial. O `tree_digest` embrulhado só *agenda* o
    hazard: a certificação lê o arquivo ainda legível e o chmod 000 acontece entre a
    certidão e a cópia, que é a janela real (o agente mexe na quarentena). O erro em
    si é do kernel, não de um stub.
    """
    entry_id, payload = stored(tmp_path, book, size=8192)
    locked = payload / "travado.bin"
    locked.write_bytes(b"z" * 512)
    # A certidão tem de cobrir o arquivo novo ANTES do hazard: sem esta linha o
    # `restore` recusaria por digest divergente (que é o teste de cima) e o
    # `copytree` nunca seria chamado. Renovar o `sha256` no ledger é o que o
    # `release_item` faria de verdade ao registrar o clone.
    book.append(**{**book.records()[entry_id].to_dict(),
                   "sha256": release.tree_digest(payload)[0]})
    verdadeiro = release.tree_digest

    def fecha_depois_da_certidao(p):
        digest, total = verdadeiro(p)
        locked.chmod(0o000)
        return digest, total

    monkeypatch.setattr(release, "tree_digest", fecha_depois_da_certidao)
    try:
        res = release.restore_item(entry_id, ledger=book, confirm=True,
                                   statvfs_fn=lambda p: _vfs(20 * GIB),
                                   mounts_fn=lambda: (),
                                   allowed_roots=[tmp_path], now=NOW)
    finally:
        locked.chmod(0o644)
    assert res.ok is False and "cópia" in res.reason
    assert payload.exists(), "a SSD mantém o item"
    assert not (tmp_path / "sessao-velha").exists(), "a metade devolvida foi desfeita"
    assert book.records()[entry_id].state == STATE_RELEASED


def test_expire_dry_run_lists_exactly_what_it_would_delete(tmp_path, book):
    old, old_payload = stored(tmp_path, book, name="antiga", days=40)
    fresh, fresh_payload = stored(tmp_path, book, name="nova", days=1)
    res = release.expire_over_budget(ledger=book, now=NOW)
    assert res.ok is True
    assert res.victims == (old,)
    assert "antiga" in res.reason and "nova" not in res.reason
    assert old_payload.exists(), "dry-run não apaga nada"


def test_expire_needs_two_flags(tmp_path, book):
    stored(tmp_path, book, name="antiga", days=40)
    half = release.expire_over_budget(ledger=book, confirm=True, now=NOW)
    assert half.ok is False and "--irreversivel" in half.reason
    other = release.expire_over_budget(ledger=book, irreversible=True, now=NOW)
    assert other.ok is False and "--confirmar" in other.reason


def test_expire_removes_oldest_first_and_audits_each(tmp_path, book, audit):
    old, old_payload = stored(tmp_path, book, name="antiga", days=40, size=2048)
    fresh, fresh_payload = stored(tmp_path, book, name="nova", days=1, size=1024)
    res = release.expire_over_budget(ledger=book, audit=audit, confirm=True,
                                     irreversible=True, now=NOW,
                                     allowed_roots=[tmp_path])
    assert res.ok is True and res.victims == (old,)
    assert not old_payload.exists() and fresh_payload.exists()
    assert book.records()[old].state == "expired"
    assert book.retained_bytes() == 1024
    assert [r["kind"] for r in audit.tail(4)][-1] == "tmpfs.expire"
    # §7: a linha da transição aponta para o evento que a criou
    assert book.records()[old].audit_event_id == audit.tail(4)[-1]["event_id"]


def test_a_restore_line_points_at_its_own_audit_event(tmp_path, book, audit):
    entry_id, payload = stored(tmp_path, book)
    res = release.restore_item(entry_id, ledger=book, audit=audit, confirm=True,
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               mounts_fn=lambda: (),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is True
    record = book.records()[entry_id]
    assert record.state == "restored"
    assert record.audit_event_id, "a linha da transição aponta para o evento"
    assert [(e["event_id"], e["kind"]) for e in audit.tail(4)] == [
        (record.audit_event_id, "tmpfs.restore")]


def test_expire_reports_the_bytes_it_frees_even_when_a_path_is_already_gone(tmp_path, book):
    gone, payload = stored(tmp_path, book, name="sumida", days=40, size=4096)
    shutil.rmtree(payload)
    res = release.expire_over_budget(ledger=book, confirm=True, irreversible=True,
                                     now=NOW, allowed_roots=[tmp_path])
    assert res.ok is True and res.victims == (gone,)
    assert res.errors, "o ledger sabia de um payload que não existe mais"


def test_a_copytree_failure_on_the_release_side_refuses_without_a_traceback(tmp_path, book):
    """A liberação no mesmo hazard, pelo mesmo motivo: resultado, não exceção.

    Arquivo ilegível *dentro* do item faz `copytree` ajuntar o `PermissionError` num
    `shutil.Error` — que é subclasse de `OSError`, e é isso que faz o `except OSError`
    do bloco de cópia pegar o agregado, desfazer o clone parcial e devolver
    `ReleaseResult`. Nada muda no código por este teste; ele existe porque a cláusula
    é a fronteira entre "a CLI (T12) imprime uma recusa com exit 1" e "a CLI estoura um
    traceback no terminal do usuário". Trocar o `except` por um tipo que não pega
    `shutil.Error` faz este teste morrer de erro em vez de recusar.
    """
    plan, it, src = item(tmp_path)
    locked = src / "travado.bin"
    locked.write_bytes(b"z" * 512)
    locked.chmod(0o000)
    try:
        res = release.release_item(plan, it, ledger=book, confirm=True,
                                   dest_root=tmp_path / "retida", entry_fn=free(),
                                   statvfs_fn=lambda p: _vfs(20 * GIB),
                                   allowed_roots=roots(tmp_path), now=NOW)
    finally:
        locked.chmod(0o644)
    assert res.ok is False and "cópia" in res.reason
    assert locked.exists(), "a origem está intacta, inclusive o que não pôde ser lido"
    assert not any((tmp_path / "retida").rglob("*.bin")), "a metade copiada foi desfeita"
    assert book.retained_bytes() == 0
    assert book.find(str(src)).state == STATE_DROPPED, \
        "a cópia que falhou fecha a própria linha: nada fica pendurado"


# --------------------------------------------------- entrega 4: staging e recover


def _release(plan, it, book, tmp_path, **over):
    kwargs = dict(ledger=book, confirm=True, dest_root=tmp_path / "retida",
                  entry_fn=free(), statvfs_fn=lambda p: _vfs(20 * GIB),
                  allowed_roots=roots(tmp_path), now=NOW)
    kwargs.update(over)
    return release.release_item(plan, it, **kwargs)


def crash_during_copy(monkeypatch):
    """Queda no meio da cópia: `KeyboardInterrupt` não é `OSError`.

    O `except OSError` do bloco de cópia não pega `BaseException` — exatamente como
    um kill no meio do caminho. O que sobrar (meia cópia + linha `staging`) é o que
    o `recover` tem de resolver; nada pode depender de o `except` ter rodado. Só a
    primeira cópia morre: depois da recuperação, o mesmo chão volta a funcionar.
    """
    real = shutil.copytree
    first = []

    def boom(src, dst, **kw):
        if first:
            return real(src, dst, **kw)
        first.append(1)
        Path(dst).mkdir(parents=True, exist_ok=True)
        (Path(dst) / "meio.bin").write_bytes(b"x" * 128)
        raise KeyboardInterrupt

    monkeypatch.setattr(release.shutil, "copytree", boom)
    return real


def crash_after_copy(monkeypatch):
    """Queda depois da cópia e antes da certificação: clone completo, sem certidão.

    Só a primeira leitura de digest morre; a segunda (que representaria outra
    execução do processo) volta ao normal.
    """
    real = release.tree_digest
    first = []

    def boom(path, *a, **kw):
        if not first:
            first.append(path)
            raise KeyboardInterrupt
        return real(path, *a, **kw)

    monkeypatch.setattr(release, "tree_digest", boom)


def test_the_ledger_knows_the_clone_before_the_first_byte_is_copied(tmp_path, book,
                                                                    monkeypatch):
    """A ordem invertida é a correção da R11: o meio do caminho é escrito ANTES.

    A espiã lê o ledger de dentro da própria cópia: quando o `copytree` roda, a única
    linha vigente já é `staging`. Sem ela, uma queda aqui deixaria um destino órfão
    que nem `retained_bytes()` nem o `recover` veriam.
    """
    plan, it, src = item(tmp_path)
    real = shutil.copytree
    seen = []

    def spy(a, b, **kw):
        seen.extend(r.state for r in book.records().values())
        return real(a, b, **kw)

    monkeypatch.setattr(release.shutil, "copytree", spy)
    res = _release(plan, it, book, tmp_path)
    assert res.ok is True
    assert seen == [STATE_STAGING], "o ledger tem de conhecer o clone antes do byte"
    assert book.records()[res.entry_id].state == STATE_RELEASED


def test_an_interrupted_copy_is_recovered_and_never_leaves_an_orphan_clone(
        tmp_path, book, audit, monkeypatch):
    """A queda no meio da cópia vira estado recuperável, não lixo invisível.

    O caminho inteiro: a meia cópia fica registrada (`staging`), a origem continua
    intacta, a próxima liberação é recusada apontando o `recover`, o clone
    redundante é descartado com a linha fechando como `dropped`, e a liberação
    funcionar de novo é a prova de que nada ficou preso.
    """
    plan, it, src = item(tmp_path)
    crash_during_copy(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        _release(plan, it, book, tmp_path)

    record = book.find(str(src))
    assert record.state == STATE_STAGING, "a queda virou uma linha, não um órfão"
    assert (src / "blob.bin").exists(), "a origem nunca foi tocada"
    assert (Path(record.stored) / "meio.bin").exists(), "a meia cópia ficou para o recover"

    again = _release(plan, it, book, tmp_path)
    assert again.ok is False
    assert "staging" in again.reason and "recover" in again.reason, again.reason

    out = release.recover_staging(ledger=book, audit=audit, confirm=True,
                                  allowed_roots=roots(tmp_path))
    assert out.ok is True and out.dropped == (record.entry_id,)
    assert not any((tmp_path / "retida").rglob("meio.bin")), "o clone inacabado saiu"
    assert book.find(str(src)).state == STATE_DROPPED
    assert any(e["kind"] == "tmpfs.recover" and e["outcome"] == STATE_DROPPED
               for e in audit.tail(10)), "a transição tem o próprio evento"

    res = _release(plan, it, book, tmp_path)
    assert res.ok is True and not src.exists(), "o caminho volta a ser liberável"


def test_a_crash_after_the_copy_but_before_certification_is_recoverable(tmp_path, book,
                                                                        monkeypatch):
    """Clone completo e não certificado também é staging — e também é descartável.

    Certificar só vale contra a origem viva; o clone sem certidão não pode virar
    `partial` por suposição. Com a origem presente, a recuperação o descarta.
    """
    plan, it, src = item(tmp_path)
    crash_after_copy(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        _release(plan, it, book, tmp_path)

    record = book.find(str(src))
    assert record.state == STATE_STAGING
    clone = Path(record.stored) / "blob.bin"
    assert clone.exists() and clone.stat().st_size == 4096, "a cópia terminou inteira"

    out = release.recover_staging(ledger=book, confirm=True,
                                  allowed_roots=roots(tmp_path))
    assert out.dropped == (record.entry_id,) and not clone.exists()
    assert (src / "blob.bin").exists(), "a âncora da decisão continua intacta"


def test_recovery_never_deletes_the_clone_when_the_origin_is_gone(tmp_path, book,
                                                                   monkeypatch):
    """Origem sumida: o clone não certificado pode ser a única cópia — não se apaga.

    Este é o outro lado da R11: apagar por adivinhação seria destruição; a saída
    honesta é manter, dizer que a decisão é manual e nunca deixar o `restore`
    tratar um clone não certificado como payload devolvível.
    """
    plan, it, src = item(tmp_path)
    crash_after_copy(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        _release(plan, it, book, tmp_path)
    record = book.find(str(src))
    clone = Path(record.stored) / "blob.bin"
    shutil.rmtree(src)  # a origem sumiu (agente, usuário, outro processo)

    dry = release.recover_staging(ledger=book, confirm=False,
                                  allowed_roots=roots(tmp_path))
    assert dry.dry_run is True and dry.dropped == () and dry.kept == (record.entry_id,)
    assert clone.exists(), "dry-run não toca em nada"

    out = release.recover_staging(ledger=book, confirm=True,
                                  allowed_roots=roots(tmp_path))
    assert out.dropped == () and out.kept == (record.entry_id,)
    assert clone.exists(), "o único clone não certificado não pode ser apagado"
    assert any("decisão manual" in n for n in out.notes)
    assert book.find(str(src)).state == STATE_STAGING, "a decisão continua aberta"

    res = release.restore_item(record.entry_id, ledger=book, confirm=True,
                               allowed_roots=roots(tmp_path))
    assert res.ok is False and "staging" in res.reason and "recover" in res.reason, \
        "clone não certificado não vira volume, nem pela volta"


def test_recover_dry_run_separates_discardable_from_manual(tmp_path, book, monkeypatch):
    """O dry-run é o inventário: o que seria descartado e o que pede gente."""
    plan, it, src = item(tmp_path)
    crash_during_copy(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        _release(plan, it, book, tmp_path)
    discardable = book.find(str(src))

    plan2, it2, src2 = item(tmp_path, name="qoder-cli-1001",
                            allow=(str(tmp_path / "qoder-cli-1001"),
                                   str(tmp_path / "qoder-cli-1001" / "*")))
    planner_item = plan2.find(str(src2))
    crash_during_copy(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        release.release_item(plan2, planner_item, ledger=book, confirm=True,
                             dest_root=tmp_path / "retida", entry_fn=free(),
                             statvfs_fn=lambda p: _vfs(20 * GIB),
                             allowed_roots=roots(tmp_path), now=NOW)
    gone = book.find(str(src2))
    shutil.rmtree(src2)

    dry = release.recover_staging(ledger=book, confirm=False,
                                  allowed_roots=roots(tmp_path))
    assert dry.dropped == (discardable.entry_id,)
    assert dry.kept == (gone.entry_id,)
    assert book.find(str(src)).state == STATE_STAGING
    assert book.find(str(src2)).state == STATE_STAGING

    out = release.recover_staging(ledger=book, confirm=True,
                                  allowed_roots=roots(tmp_path))
    assert out.dropped == (discardable.entry_id,) and out.kept == (gone.entry_id,)


def test_recover_refuses_a_clone_outside_the_allowed_roots_and_keeps_it(
        tmp_path, book, monkeypatch):
    """O guard vale também para o clone: recusa relatada, entrada segue staging."""
    plan, it, src = item(tmp_path)
    crash_during_copy(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        _release(plan, it, book, tmp_path)
    record = book.find(str(src))

    out = release.recover_staging(ledger=book, confirm=True,
                                  allowed_roots=[tmp_path / "fora"])
    assert out.ok is False and out.dropped == ()
    assert any("allowed root" in e for e in out.errors)
    assert Path(record.stored).exists(), "sem permissão de tocar, não se toca"
    assert book.find(str(src)).state == STATE_STAGING


def test_a_failed_copy_closes_its_staging_line_and_frees_the_retry(tmp_path, book,
                                                                    monkeypatch):
    """Falha pega pelo `except` não deixa linha pendurada nem caminho preso."""
    plan, it, src = item(tmp_path)
    real = shutil.copytree
    first = []

    def boom_once(a, b, **kw):
        if not first:
            first.append(1)
            raise OSError(28, "No space left on device")
        return real(a, b, **kw)

    monkeypatch.setattr(release.shutil, "copytree", boom_once)
    res = _release(plan, it, book, tmp_path)
    assert res.ok is False and "cópia" in res.reason
    assert book.find(str(src)).state == STATE_DROPPED
    assert book.retained_bytes() == 0

    good = _release(plan, it, book, tmp_path)
    assert good.ok is True and not src.exists()


def test_recover_with_a_clean_ledger_says_there_is_nothing(tmp_path, book):
    out = release.recover_staging(ledger=book, confirm=True,
                                  allowed_roots=roots(tmp_path))
    assert out.ok is True and out.dropped == () and out.kept == ()
    assert "nada a recuperar" in out.reason
    dry = release.recover_staging(ledger=book, confirm=False,
                                  allowed_roots=roots(tmp_path))
    assert dry.dry_run is False and "nada a recuperar" in dry.reason


def _write_raw_ledger_row(book, **row):
    """Uma linha como uma versão futura (ou uma edição à mão) a deixaria.

    `Ledger.append` preenche tudo; escrever o JSON cru é o que fabrica o registro
    degradado que o `_hydrate` aceita com campos vazios.
    """
    book.path.parent.mkdir(parents=True, exist_ok=True)
    with book.path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def test_a_malformed_staging_row_never_authorizes_deleting_the_cwd(tmp_path, book):
    """Linha quebrada não vira mutação: `Path("")` é `.` e `.` não se apaga.

    Duas degradações: (a) linha sem campo obrigatório — o `_hydrate` zera tudo e a
    entrada vira decisão manual, porque nem a origem é legível; (b) linha hidratável
    com `stored=""` — sem o portão de caminho absoluto, `.` passaria pelo guard
    (raízes incluem o cwd de propósito) e o `remove_fn` seria chamado com o
    diretório de trabalho. O spy prova que nenhuma remoção foi *tentada*.
    """
    clone = tmp_path / "clone-real"
    clone.mkdir()
    _write_raw_ledger_row(book, ts="2026-01-01T00:00:00Z", entry_id="mau-degradada",
                          src=str(tmp_path / "origem"), volume="/tmp",
                          state="staging", bytes=0, sha256="", age_days=0.0,
                          matched_pattern=None, holder_pids=(),
                          action_id="tmpfs.release")
    _write_raw_ledger_row(book, ts="2026-01-01T00:00:01Z", entry_id="mau-vazia",
                          src=str(clone), volume="/tmp", stored="",
                          state="staging", bytes=0, sha256="", age_days=0.0,
                          matched_pattern=None, holder_pids=(),
                          action_id="tmpfs.release", audit_event_id="")
    tentados = []

    out = release.recover_staging(ledger=book, confirm=True,
                                  allowed_roots=[tmp_path, Path.cwd()],
                                  remove_fn=tentados.append)

    assert out.dropped == (), "nenhuma linha degradada autoriza remoção"
    assert out.kept == ("mau-degradada",), "sem origem legível, nada é tocado"
    assert tentados == [], "o portão de caminho absoluto barra `.` antes do remove"
    assert any("absoluto" in e for e in out.errors)
    assert clone.exists()
    assert book.find("mau-degradada").state == STATE_STAGING
    assert book.find("mau-vazia").state == STATE_STAGING


def test_staging_stays_out_of_the_budget_and_the_expire(tmp_path, book, monkeypatch):
    """Bytes não certificados não orçam, e o expire jamais apaga um staging.

    Com a origem possivelmente sumida, o clone `staging` pode ser a única cópia:
    contá-lo no orçamento convidaria o `expire` a apagá-lo — exatamente o que não
    pode acontecer.
    """
    plan, it, src = item(tmp_path)
    crash_during_copy(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        _release(plan, it, book, tmp_path)
    record = book.find(str(src))

    assert record.state == STATE_STAGING
    assert book.retained_count() == 0 and book.retained_bytes() == 0, \
        "bytes não certificados não entram no orçamento"
    out = release.expire_over_budget(ledger=book, confirm=True, irreversible=True,
                                     now=NOW + 40 * DAY, allowed_roots=roots(tmp_path))
    assert out.victims == ()
    assert (Path(record.stored) / "meio.bin").exists()
    assert book.find(str(src)).state == STATE_STAGING


def test_a_malformed_expire_victim_is_reported_never_deleted(tmp_path, book):
    """A mesma linha degradada no expire: vítima sem caminho absoluto é aviso."""
    clone = tmp_path / "clone-real"
    clone.mkdir()
    _write_raw_ledger_row(book, ts=time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                 time.gmtime(NOW - 40 * DAY)),
                          entry_id="mau-vencida", src=str(tmp_path / "origem"),
                          volume="/tmp", state="released",
                          bytes=MAX_RETAINED_BYTES + 1, sha256="", age_days=40.0,
                          matched_pattern=None, holder_pids=(),
                          action_id="tmpfs.release")

    out = release.expire_over_budget(ledger=book, confirm=True, irreversible=True,
                                     allowed_roots=roots(tmp_path), now=NOW)

    assert out.victims == ()
    assert any("absoluto" in e for e in out.errors), out.errors
    assert clone.exists()


def test_a_malformed_restore_is_refused_before_touching_anything(tmp_path, book):
    _write_raw_ledger_row(book, ts="2026-01-01T00:00:00Z", entry_id="mau-restore",
                          src=str(tmp_path / "origem"), volume="/tmp",
                          state="released", bytes=10, sha256="", age_days=0.0,
                          matched_pattern=None, holder_pids=(),
                          action_id="tmpfs.release")

    res = release.restore_item("mau-restore", ledger=book, confirm=True,
                               allowed_roots=roots(tmp_path))

    assert res.ok is False and "absoluto" in res.reason
    assert not (tmp_path / "origem").exists()


def _corrupt_ledger(book):
    book.path.parent.mkdir(parents=True, exist_ok=True)
    with book.path.open("a", encoding="utf-8") as fh:
        fh.write("{linha quebrada}\n")


def test_an_inconsistent_ledger_blocks_every_mutation(tmp_path, book, audit):
    """Linha ilegível fecha a porta dos quatro atos: decidir com mapa incompleto é a R11.

    A leitura continua mostrando o que dá para ler e nomeia a linha; o que não
    pode é copiar, restaurar, expirar ou descartar clone em cima de um registro
    que talvez esconda um clone ativo ou uma liberação inacabada.
    """
    plan, it, src = item(tmp_path)
    book.append(entry_id="retido", state=STATE_RELEASED, action_id="tmpfs.release",
                src=str(tmp_path / "antigo"), volume="/tmp",
                stored=str(tmp_path / "retida" / "antigo"), bytes=4096,
                sha256="ab" * 32, age_days=1.0)
    _corrupt_ledger(book)

    out = release.release_item(plan, it, ledger=book, audit=audit, confirm=True,
                               dest_root=tmp_path / "retida",
                               allowed_roots=roots(tmp_path))
    assert out.ok is False and "ledger inconsistente" in out.reason

    out = release.restore_item("retido", ledger=book, audit=audit, confirm=True,
                               allowed_roots=roots(tmp_path))
    assert out.ok is False and "ledger inconsistente" in out.reason

    out = release.expire_over_budget(ledger=book, audit=audit, confirm=True,
                                     irreversible=True, allowed_roots=roots(tmp_path))
    assert out.ok is False and "ledger inconsistente" in out.reason

    out = release.recover_staging(ledger=book, audit=audit, confirm=True,
                                  allowed_roots=roots(tmp_path))
    assert out.ok is False and "ledger inconsistente" in out.reason

    dry = release.recover_staging(ledger=book, confirm=False,
                                  allowed_roots=roots(tmp_path))
    assert dry.ok is False and "ledger inconsistente" in dry.reason, \
        "nem o dry-run decide com mapa incompleto"

    assert src.exists() and (src / "blob.bin").exists(), "nada foi tocado"
    assert not (tmp_path / "retida").exists()
    rows, problems = book.load()
    assert len(rows) == 1 and problems, "o relatório continua nomeando a linha"
