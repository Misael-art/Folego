"""Disk hygiene M5 — quarantine: reclaim space reversibly, purge only on a second call."""
import json
import os

import pytest

from folego.actions.disk.quarantine import Quarantine
from folego.safely.audit import AuditLog


@pytest.fixture
def area(fake_home):
    """The user tree being reclaimed, isolated by the fake_home fixture."""
    src = fake_home / ".cache" / "oldproject"
    (src / "build").mkdir(parents=True)
    (src / "build" / "artifact.bin").write_bytes(b"z" * 4096)
    (src / "note.txt").write_text("oi")
    return src


def make_quarantine(fake_home, audit=None, stat_fn=os.stat):
    root = fake_home / ".local" / "share" / "folego" / "quarantine"
    return Quarantine(root, allowed_roots=[fake_home], audit=audit, stat_fn=stat_fn)


def test_move_in_frees_the_original_path_and_keeps_bytes(area, fake_home):
    q = make_quarantine(fake_home)

    entry = q.move_in(area)

    assert not area.exists()
    assert os.path.isdir(entry.stored)
    assert entry.bytes == 4096 + len("oi")
    assert q.entries()[entry.entry_id].state == "stored"


def test_restore_puts_everything_back(area, fake_home):
    q = make_quarantine(fake_home)
    entry = q.move_in(area)

    result = q.restore(entry.entry_id)

    assert result.ok is True
    assert (area / "build" / "artifact.bin").read_bytes() == b"z" * 4096
    assert (area / "note.txt").read_text() == "oi"
    assert q.entries()[entry.entry_id].state == "restored"


def test_manifest_survives_reload(area, fake_home):
    q = make_quarantine(fake_home)
    entry = q.move_in(area)

    reloaded = make_quarantine(fake_home)

    assert reloaded.entries()[entry.entry_id].original == str(area)
    assert reloaded.entries()[entry.entry_id].bytes == entry.bytes


def test_purge_is_explicit_and_idempotent(area, fake_home):
    q = make_quarantine(fake_home)
    entry = q.move_in(area)

    assert q.purge(entry.entry_id).ok is True
    assert not os.path.exists(entry.stored)
    second = q.purge(entry.entry_id)
    assert second.ok is False
    assert "purged" in second.reason


def test_restore_refuses_when_original_reappeared(area, fake_home):
    q = make_quarantine(fake_home)
    entry = q.move_in(area)
    area.mkdir(parents=True)
    (area / "novo.txt").write_text("dados novos")

    result = q.restore(entry.entry_id)

    assert result.ok is False
    assert "already exists" in result.reason
    assert (area / "novo.txt").read_text() == "dados novos"
    assert q.entries()[entry.entry_id].state == "stored"


def test_blacklisted_and_foreign_paths_are_refused(area, fake_home):
    q = make_quarantine(fake_home)

    for bad in ("/mnt/sdcard/.cache", "/home/other/.cache", "/etc/fonts"):
        with pytest.raises(PermissionError, match="refused"):
            q.move_in(bad)


def test_cross_device_move_is_refused(area, fake_home):
    real_stat = os.stat

    def other_device_stat(path, *args, **kwargs):
        st = real_stat(path, *args, **kwargs)
        if str(path) == str(area):

            class Shifted:
                st_dev = st.st_dev + 1
                st_mode = st.st_mode
                st_ino = st.st_ino
                st_size = st.st_size
                st_uid = st.st_uid

            return Shifted()
        return st

    q = make_quarantine(fake_home, stat_fn=other_device_stat)

    with pytest.raises(PermissionError, match="cross-device"):
        q.move_in(area)
    assert area.exists()


def test_symlink_is_refused(fake_home, tmp_path):
    victim = tmp_path / "real"
    victim.mkdir()
    (victim / "f.bin").write_bytes(b"x")
    (fake_home / ".cache").mkdir(parents=True, exist_ok=True)
    link = fake_home / ".cache" / "link"
    link.symlink_to(victim)

    q = make_quarantine(fake_home)
    with pytest.raises(PermissionError, match="refused"):
        q.move_in(link)
    assert victim.exists()


def test_every_move_is_audited(area, fake_home):
    audit = AuditLog(fake_home / ".local" / "state" / "folego" / "audit.jsonl")
    q = make_quarantine(fake_home, audit=audit)

    entry = q.move_in(area)
    q.restore(entry.entry_id)

    kinds = [(r["kind"], r["outcome"], r["action_id"]) for r in audit.tail(10)]
    assert ("disk.quarantine", "stored", entry.entry_id) in kinds
    assert ("disk.restore", "restored", entry.entry_id) in kinds


def test_reconcile_repairs_an_interrupted_move(area, fake_home):
    """Crash window: manifest says planned, the rename already happened."""
    q = make_quarantine(fake_home)
    entry = q.move_in(area)
    raw = json.loads(q.manifest_path.read_text())
    raw["entries"][0]["state"] = "planned"
    q.manifest_path.write_text(json.dumps(raw))

    report = q.reconcile()

    assert report.repaired == (entry.entry_id,)
    assert report.dropped == () and report.manual == ()
    assert q.entries()[entry.entry_id].state == "stored"


def test_reconcile_leaves_true_planned_entries_alone(area, fake_home):
    q = make_quarantine(fake_home)
    q.root.mkdir(parents=True, exist_ok=True)
    # formato legado (lista crua): continua legível, e migra na primeira escrita
    q.manifest_path.write_text(json.dumps([{
        "entry_id": "ghost-1", "original": str(area / "ghost"),
        "stored": str(q.root / "ghost-1"), "bytes": 0, "state": "planned",
        "moved_at": "", "action_id": "disk.quarantine"}]))

    report = q.reconcile()

    assert report.repaired == () and report.dropped == ()
    assert report.manual == ("ghost-1",), "ambíguo não vira remoção nem fechamento"
    assert q.entries()["ghost-1"].state == "planned"


def test_reconcile_closes_a_planned_row_that_never_renamed(area, fake_home):
    """Origem intacta e sem payload: o rename nunca aconteceu; fechar é honesto."""
    q = make_quarantine(fake_home)
    q.root.mkdir(parents=True, exist_ok=True)
    q.manifest_path.write_text(json.dumps([{
        "entry_id": "no-rename", "original": str(area),
        "stored": str(q.root / "no-rename"), "bytes": 0, "state": "planned",
        "moved_at": "", "action_id": "disk.quarantine"}]))

    report = q.reconcile()

    assert report.dropped == ("no-rename",) and report.repaired == ()
    assert q.entries()["no-rename"].state == "dropped"
    assert area.exists(), "nenhum dado tocado"


def test_reconcile_leaves_ambiguous_transitions_for_manual(area, fake_home):
    """Ambos existem: o usuário recriou a origem e o clone é dado real — nada de auto."""
    q = make_quarantine(fake_home)
    q.root.mkdir(parents=True, exist_ok=True)
    stored = q.root / "ambos"
    stored.mkdir()
    q.manifest_path.write_text(json.dumps([{
        "entry_id": "ambos", "original": str(area), "stored": str(stored),
        "bytes": 0, "state": "planned", "moved_at": "",
        "action_id": "disk.quarantine"}]))

    report = q.reconcile()

    assert report.manual == ("ambos",) and report.repaired == () and report.dropped == ()
    assert q.entries()["ambos"].state == "planned"


def test_move_in_refuses_inside_the_quarantine_root_itself(area, fake_home):
    q = make_quarantine(fake_home)
    entry = q.move_in(area)

    with pytest.raises(PermissionError, match="quarantine"):
        q.move_in(entry.stored)


def test_empty_dir_and_hidden_names_roundtrip(fake_home):
    src = fake_home / ".cache" / ".hidden.thing"
    src.mkdir(parents=True)
    q = make_quarantine(fake_home)

    entry = q.move_in(src)
    assert entry.bytes == 0
    assert q.restore(entry.entry_id).ok is True
    assert src.is_dir()


def test_manifest_is_owner_only(area, fake_home):
    q = make_quarantine(fake_home)
    q.move_in(area)

    assert (q.manifest_path.stat().st_mode & 0o077) == 0


def test_the_manifest_is_versioned_and_keeps_the_previous_generation(area, fake_home):
    q = make_quarantine(fake_home)
    entry = q.move_in(area)

    payload = json.loads(q.manifest_path.read_text())
    assert payload["schema"] == 1
    assert payload["entries"][0]["state"] == "stored"
    backup = q.manifest_path.with_name("manifest.json.bak")
    assert json.loads(backup.read_text())["entries"][0]["state"] == "planned", \
        "o backup é a geração imediatamente anterior"

    q.restore(entry.entry_id)

    assert json.loads(backup.read_text())["entries"][0]["state"] == "stored"
    assert (backup.stat().st_mode & 0o077) == 0


def test_a_legacy_list_manifest_is_read_and_migrated_with_backup(area, fake_home):
    q = make_quarantine(fake_home)
    stored = q.root / "antigo"
    stored.mkdir(parents=True)
    (stored / "f.bin").write_bytes(b"aaa")
    legacy = [{
        "entry_id": "antigo", "original": str(area), "stored": str(stored),
        "bytes": 3, "state": "stored", "moved_at": "2026-01-01T00:00:00Z",
        "action_id": "disk.quarantine"}]
    q.manifest_path.write_text(json.dumps(legacy))

    assert q.entries()["antigo"].state == "stored", "lista crua continua legível"

    assert q.purge("antigo").ok is True  # a primeira escrita migra o formato

    backup = q.manifest_path.with_name("manifest.json.bak")
    assert json.loads(backup.read_text()) == legacy, "o original fica no backup"
    assert json.loads(q.manifest_path.read_text())["schema"] == 1


def test_a_corrupt_manifest_blocks_every_mutation(area, fake_home):
    """R13: corrupção bloqueia mutação — nunca se recomeça de um manifesto vazio."""
    q = make_quarantine(fake_home)
    q.root.mkdir(parents=True, exist_ok=True)
    q.manifest_path.write_text("lixo{")

    with pytest.raises(PermissionError, match="inconsistente"):
        q.move_in(area)

    restored = q.restore("qualquer")
    assert restored.ok is False and "inconsistente" in restored.reason
    purged = q.purge("qualquer")
    assert purged.ok is False and "inconsistente" in purged.reason
    assert area.exists(), "nada foi tocado"
    assert q.entries() == {}
    assert q.inspect()[1], "o problema é relatado, não engolido"


def test_a_relative_path_in_the_manifest_blocks_mutation(area, fake_home):
    """`Path("")` é `.`: caminho registrado tem de ser absoluto, senão não se muta."""
    q = make_quarantine(fake_home)
    q.root.mkdir(parents=True, exist_ok=True)
    q.manifest_path.write_text(json.dumps({"schema": 1, "entries": [{
        "entry_id": "mau", "original": str(area), "stored": "relativo/x",
        "bytes": 0, "state": "stored", "moved_at": "", "action_id": "disk.quarantine"}]}))

    out = q.purge("mau")

    assert out.ok is False and "absoluto" in out.reason
    assert area.exists()


def test_a_payload_outside_the_private_root_is_a_problem(area, fake_home, tmp_path):
    """O guard aceita qualquer caminho sob a home; o payload tem de estar na raiz.

    Sem o confinamento, um manifesto edito apontaria o `purge` para outro lugar
    do disco — entrada, payload e raiz são uma relação validada, não um convite.
    """
    q = make_quarantine(fake_home)
    q.root.mkdir(parents=True, exist_ok=True)
    fora = tmp_path / "fora-da-raiz"
    fora.mkdir()
    q.manifest_path.write_text(json.dumps({"schema": 1, "entries": [{
        "entry_id": "fugitivo", "original": str(area), "stored": str(fora),
        "bytes": 0, "state": "stored", "moved_at": "",
        "action_id": "disk.quarantine"}]}))

    out = q.purge("fugitivo")

    assert out.ok is False and "raiz privada" in out.reason
    assert fora.exists(), "nada fora da raiz privada pode ser tocado"


def test_reconcile_refuses_a_corrupt_manifest_without_writing(area, fake_home):
    q = make_quarantine(fake_home)
    q.root.mkdir(parents=True, exist_ok=True)
    q.manifest_path.write_text("lixo{")

    report = q.reconcile()

    assert report.problems and not report.mutated
    assert q.manifest_path.read_text() == "lixo{", "nada foi reescrito por cima"
