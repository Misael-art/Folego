"""A promessa deste arquivo é tirar bytes da RAM sem perder nenhum.

Cross-device é o ponto, não um bug: o `Quarantine.move_in` do M5 recusa rename
entre dispositivos porque lá a promessa é zero-copy; aqui a promessa é liberar
memória, então o movimento é explicitamente copy → verify → unlink, e o ledger
registra o meio do caminho.
"""
import os
from pathlib import Path

import pytest

from deck_wellness.actions.tmpfs import release
from deck_wellness.actions.tmpfs.inventory import TmpfsEntry
from deck_wellness.actions.tmpfs.ledger import (MAX_RETAINED_BYTES, STATE_PARTIAL,
                                                 STATE_RELEASED, STATE_RESTORED, Ledger)
from deck_wellness.actions.tmpfs.plan import build_plan
from deck_wellness.actions.tmpfs.policy import Policy
from deck_wellness.core.tmpfs import TmpfsVolume
from deck_wellness.safely.audit import AuditLog

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
