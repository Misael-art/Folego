"""Classificar sem adivinhar: tipo, dono, idade, monte, holder — por item.

A idade sai do arquivo mais novo *dentro* da árvore, não do mtime do diretório:
uma pasta de sessão pode ter mtime antigo e escrita de agora, e idade antiga
errada aqui é exatamente o acidente que estamos evitando.
"""
import os
import socket

import pytest

from deck_wellness.actions.tmpfs import holders, inventory
from deck_wellness.core.tmpfs import TmpfsVolume

NOW = 1_700_000_000.0
EMPTY = holders.HolderIndex({}, 0, 0)


def volume_dir(tmp_path):
    root = tmp_path / "tmp"
    root.mkdir()
    return root


def child(root, name, *, age_d=10.0, is_dir=False, content="x"):
    path = root / name
    if is_dir:
        (path / "inner").mkdir(parents=True)
        target = path / "inner"
    else:
        path.write_text(content)
        target = path
    stamp = NOW - age_d * 86_400
    os.utime(target, (stamp, stamp))
    return path


def test_age_uses_the_newest_file_inside_the_tree(tmp_path):
    root = volume_dir(tmp_path)
    session = child(root, "sessao", age_d=40.0, is_dir=True)
    fresh = session / "saida.log"
    fresh.write_text("agora")
    os.utime(fresh, (NOW - 60, NOW - 60))
    # escrever move o mtime do diretório para o relógio real de verdade; a cena do
    # docstring é mtime do diretório velho com escrita nova dentro — refaz o velho.
    # (sem isto, measure_tree devolve o mtime do diretório como mais novo e a idade
    # do pai sai 0.0: o teste não poderia passar, e a mutação não teria o que matar)
    os.utime(session, (NOW - 40 * 86_400, NOW - 40 * 86_400))

    entry = inventory.entry_at(str(fresh), (), EMPTY, volume=str(root), now=NOW)
    assert entry.age_days == pytest.approx(60 / 86_400, abs=1e-6)
    parent = inventory.entry_at(str(session), (), EMPTY, volume=str(root), now=NOW)
    assert parent.age_days == pytest.approx(60 / 86_400, abs=1e-6)


def test_kind_uid_and_size(tmp_path):
    root = volume_dir(tmp_path)
    child(root, "arquivo", content="12345")
    child(root, "dir-velho", is_dir=True)
    sock = socket.socket(socket.AF_UNIX)
    sock.bind(str(root / "sock"))
    os.mkfifo(root / "fifo")

    by_name = {e.name: e for e in inventory.inventory(str(root), (), EMPTY, now=NOW)}
    assert by_name["dir-velho"].kind == "dir"
    assert by_name["arquivo"].kind == "file" and by_name["arquivo"].bytes == 5
    assert by_name["sock"].kind == "socket"
    assert by_name["fifo"].kind == "fifo"
    for entry in by_name.values():
        assert entry.uid == os.getuid() and entry.volume == str(root)
    sock.close()
    os.unlink(str(root / "sock"))


def test_a_mount_point_is_flagged_and_never_measured(tmp_path):
    root = volume_dir(tmp_path)
    doc = child(root, "doc", is_dir=True)

    def spy(tree_root, **kw):
        raise AssertionError("measure_tree não pode entrar num ponto de montagem")

    entry = inventory.entry_at(str(doc), ((str(doc), "fuse.portal"),), EMPTY,
                                volume=str(root), now=NOW, measure_fn=spy)
    assert entry.is_mount_point is True
    assert entry.bytes == 0 and entry.files == 0


def test_a_directory_that_contains_a_mount_is_flagged(tmp_path):
    root = volume_dir(tmp_path)
    run = child(root, "run", is_dir=True)
    nested = run / "user" / "1000" / "doc"
    nested.mkdir(parents=True)

    def medido_ou_explodindo(p, **kw):
        raise AssertionError(f"medida dentro de um monte: {p}")

    entry = inventory.entry_at(str(run), ((str(nested), "fuse.portal"),), EMPTY,
                               volume=str(root), now=NOW,
                               measure_fn=medido_ou_explodindo)
    assert entry.is_mount_point is False and entry.under_mount is True


def test_holder_pids_come_from_the_index(tmp_path):
    root = volume_dir(tmp_path)
    session = child(root, "qoder-cli-1000", is_dir=True)
    idx = holders.HolderIndex({str(session / "inner"): (999,)}, 1, 1)
    entry = inventory.entry_at(str(session), (), idx, volume=str(root), now=NOW)
    assert entry.holder_pids == (999,)


def test_inventory_lists_only_the_top_level_children(tmp_path):
    root = volume_dir(tmp_path)
    outer = child(root, "outer", is_dir=True)
    (outer / "inner" / "deep").mkdir(parents=True)
    assert [e.name for e in inventory.inventory(str(root), (), EMPTY, now=NOW)] == ["outer"]


def test_an_unreadable_volume_reads_as_empty_not_as_clean(tmp_path):
    """`inventory` não tem canal de erro: volume ilegível devolve () mesmo.

    Pinar isto é o que obriga T11/T13 a dizer "pode estar vazio por permissão" em
    vez de apresentar um volume EACCES como limpo.
    """
    root = volume_dir(tmp_path)
    fechado = child(root, "fechado", is_dir=True)
    (fechado / "dentro").write_text("x")
    fechado.chmod(0o000)
    try:
        assert inventory.inventory(str(fechado), (), EMPTY, now=NOW) == ()
    finally:
        fechado.chmod(0o755)


def test_symlinks_are_reported_as_symlinks(tmp_path):
    root = volume_dir(tmp_path)
    victim = child(root, "precioso")
    os.symlink(str(victim), root / "link-velho")
    by_name = {e.name: e for e in inventory.inventory(str(root), (), EMPTY, now=NOW)}
    assert by_name["link-velho"].kind == "symlink"
    assert by_name["precioso"].kind == "file"


def test_a_child_that_vanished_is_not_invented_by_the_walk(tmp_path):
    """O walk só enxerga o que existe; o `lstat_fn` injetado vale para `entry_at`."""
    root = volume_dir(tmp_path)
    child(root, "presente")
    real = os.lstat

    def lstat(path):
        if str(path).endswith("morto"):
            raise OSError(2, "no such file")
        return real(path)

    entries = inventory.inventory(str(root), (), EMPTY, now=NOW, lstat_fn=lstat)
    assert [e for e in entries if e.name == "morto"] == []
    assert [e.name for e in entries] == ["presente"]


def test_entry_at_records_a_vanished_item_instead_of_raising(tmp_path):
    root = volume_dir(tmp_path)

    def lstat(path):
        raise OSError(2, "no such file")

    entry = inventory.entry_at(str(root / "morto"), (), EMPTY, volume=str(root),
                               now=NOW, lstat_fn=lstat)
    assert entry.kind == "missing"
    assert "no such file" in entry.errors[0]


def test_truncated_measurement_is_carried_out(tmp_path):
    root = volume_dir(tmp_path)
    big = child(root, "grande", is_dir=True)

    def truncated(tree_root, **kw):
        return type("S", (), {"bytes": 1, "files": 1, "newest_ns": 0,
                              "errors": ("lento",), "truncated": True})()

    entry = inventory.entry_at(str(big), (), EMPTY, volume=str(root), now=NOW,
                               measure_fn=truncated)
    assert entry.truncated is True and entry.errors == ("lento",)


def test_scan_volume_brings_mounts_holders_and_entries_together(fake_proc, tmp_path):
    from deck_wellness.core.tmpfs import TmpfsVolume as V

    (fake_proc / "mounts").write_text(f"tmpfs {tmp_path}/tmp tmpfs rw 0 0\n")
    root = volume_dir(tmp_path)
    child(root, "tmpdeadbeef", is_dir=True)
    mounts, idx, entries = inventory.scan_volume(V(str(root), "tmpfs", 100, 1, 99),
                                                 proc_root=str(fake_proc))
    assert [m[0] for m in mounts] == [str(root)]
    assert [e.name for e in entries] == ["tmpdeadbeef"]
    assert idx.proc_count >= 0
