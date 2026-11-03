"""CLI for the disk hygiene milestone: dry-run plan, then explicit reversible reclaim."""
import json
import os
import shutil
import time

import pytest

from folego import cli
from folego.actions.disk.quarantine import Quarantine
from folego.cli import main

DAY = 86_400


@pytest.fixture
def user_tree(fake_home):
    """A cache tree nobody has touched in 60 days: a real reclaim candidate."""
    stale = fake_home / ".cache" / "projeto-antigo"
    (stale / "target").mkdir(parents=True)
    (stale / "target" / "lixo.bin").write_bytes(b"a" * 2048)
    old = time.time() - 60 * DAY
    os.utime(stale / "target" / "lixo.bin", (old, old))
    os.utime(stale / "target", (old, old))
    os.utime(stale, (old, old))
    return stale


def test_disk_plan_prints_totals_and_digest(fake_home, user_tree, capsys):
    code = main(["disk", "plan"])

    out = capsys.readouterr().out
    assert code == 0
    assert "projeto-antigo" in out
    assert "total recuperável" in out
    assert "impressão:" in out


def test_disk_plan_json_is_machine_readable(fake_home, user_tree, capsys):
    code = main(["disk", "plan", "--json"])

    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["total_bytes"] == 2048
    assert len(payload["digest"]) == 64


def _reviewed(user_tree, capsys):
    assert main(["disk", "plan", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    return next(item["action_plan"] for item in payload["items"] if item["path"] == str(user_tree))


def test_reviewed_plan_roundtrip_executes_same_id_once(fake_home, user_tree, capsys):
    plan = _reviewed(user_tree, capsys)
    argv = ["disk", "quarantine", str(user_tree), "--reviewed-plan", json.dumps(plan), "--confirmar", "--json"]
    assert main(argv) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["operation_id"] == plan["operation_id"]
    assert not user_tree.exists()
    assert main(argv) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["queried"] is True
    assert repeated["entry_id"] == first["entry_id"]
    assert len(Quarantine().entries()) == 1


def test_reviewed_plan_preserves_replaced_target(fake_home, user_tree, capsys):
    plan = _reviewed(user_tree, capsys)
    original = user_tree.with_name("preserved-original")
    user_tree.rename(original)
    user_tree.mkdir()
    (user_tree / "new-work").write_bytes(b"useful work")
    assert main(["disk", "quarantine", str(user_tree), "--reviewed-plan", json.dumps(plan),
                 "--confirmar", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "recusa"
    assert (user_tree / "new-work").read_bytes() == b"useful work"
    assert (original / "target/lixo.bin").read_bytes() == b"a" * 2048


def test_expired_review_never_moves_source(fake_home, user_tree, capsys):
    from dataclasses import replace
    from folego.orchestration.models import ActionPlan
    reviewed = ActionPlan.from_dict(_reviewed(user_tree, capsys))
    expired = replace(reviewed, created_at=1000.0, expires_at=1100.0).to_dict()
    assert main(["disk", "quarantine", str(user_tree), "--reviewed-plan", json.dumps(expired),
                 "--confirmar", "--json"]) == 1
    assert "expirado" in json.loads(capsys.readouterr().out)["reason"]
    assert (user_tree / "target/lixo.bin").read_bytes() == b"a" * 2048


def test_protected_project_is_excluded_from_estimate_and_direct_action(fake_home, user_tree, capsys):
    (user_tree / ".git").write_bytes(b"gitdir: /protected/worktree\n")
    assert main(["disk", "plan", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    item = next(row for row in payload["items"] if row["path"] == str(user_tree))
    assert item["reclaimable"] is False
    assert "action_plan" not in item
    assert payload["total_bytes"] == 0
    assert main(["disk", "quarantine", str(user_tree), "--confirmar", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["outcome"] == "recusa"
    assert (user_tree / ".git").read_bytes() == b"gitdir: /protected/worktree\n"
    assert (user_tree / "target/lixo.bin").read_bytes() == b"a" * 2048


def test_cli_does_not_announce_success_when_final_record_fails(fake_home, user_tree, capsys, monkeypatch):
    from folego.orchestration.journal import Journal
    def denied(self, result):
        raise PermissionError("final write denied")
    monkeypatch.setattr(Journal, "append_result", denied)
    assert main(["disk", "quarantine", str(user_tree), "--confirmar", "--json"]) == 5
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "desconhecido" and payload["ok"] is False
    assert "não persistido" in payload["reason"]
    assert payload["effects"]["bytes"] == 2048
    assert not user_tree.exists()


def test_disk_plan_reports_volume_usage(fake_home, user_tree, monkeypatch, capsys):
    class FakeVfs:
        def __init__(self, blocks, bavail, bfree):
            self.f_blocks, self.f_bavail, self.f_bfree = blocks, bavail, bfree
            self.f_frsize = 1024

    monkeypatch.setattr("folego.actions.disk.planner.os.statvfs",
                        lambda p: FakeVfs(1000, 900, 950))

    code = main(["disk", "plan"])

    out = capsys.readouterr().out
    assert code == 0
    assert "/tmp" in out
    assert "900,0 KB" in out


def test_disk_plan_flags_a_critical_volume(fake_home, user_tree, monkeypatch, capsys):
    class FakeVfs:
        f_frsize = 1024
        f_blocks = 1000
        f_bavail = 10
        f_bfree = 10

    monkeypatch.setattr("folego.actions.disk.planner.os.statvfs",
                        lambda p: FakeVfs())

    main(["disk", "plan"])

    assert "crítico" in capsys.readouterr().out


def test_quarantine_requires_confirmation(fake_home, user_tree, capsys):
    code = main(["disk", "quarantine", str(user_tree)])

    err = capsys.readouterr().err
    assert code == 2
    assert "--confirmar" in err
    assert user_tree.exists()


def test_quarantine_restore_roundtrip_through_the_cli(fake_home, user_tree, capsys):
    code = main(["disk", "quarantine", str(user_tree), "--confirmar"])
    assert code == 0
    stored = user_tree / "target" / "lixo.bin"
    assert not user_tree.exists()

    entries = Quarantine(allowed_roots=[fake_home]).entries()
    entry_id = next(iter(entries))
    assert entries[entry_id].bytes == 2048

    assert main(["disk", "restore", entry_id, "--confirmar"]) == 0
    capsys.readouterr()
    assert stored.read_bytes() == b"a" * 2048
    assert Quarantine(allowed_roots=[fake_home]).entries()[entry_id].state == "restored"


def test_purge_requires_the_irreversible_flag(fake_home, user_tree, capsys):
    main(["disk", "quarantine", str(user_tree), "--confirmar"])
    capsys.readouterr()
    entry_id = next(iter(Quarantine(allowed_roots=[fake_home]).entries()))

    code = main(["disk", "purge", entry_id, "--confirmar"])

    err = capsys.readouterr().err
    assert code == 2
    assert "--irreversivel" in err
    assert Quarantine(allowed_roots=[fake_home]).entries()[entry_id].state == "stored"


def test_purge_with_irreversible_flag_deletes_for_real(fake_home, user_tree, capsys):
    main(["disk", "quarantine", str(user_tree), "--confirmar"])
    capsys.readouterr()
    entry_id = next(iter(Quarantine(allowed_roots=[fake_home]).entries()))

    code = main(["disk", "purge", entry_id, "--confirmar", "--irreversivel"])

    assert code == 0
    assert Quarantine(allowed_roots=[fake_home]).entries()[entry_id].state == "purged"
    assert not user_tree.exists()


def test_disk_quarantine_json_carries_the_outcome(fake_home, user_tree, capsys):
    """Entrega 7: a mutação de disco com --json devolve o envelope do protocolo."""
    code = main(["disk", "quarantine", str(user_tree), "--confirmar", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK
    assert payload["acao"] == "quarantine" and payload["ok"] is True
    assert payload["exit"] == cli.EXIT_OK and payload["outcome"] == "sucesso"
    assert payload["original"] == str(user_tree)
    assert payload["bytes"] == 2048 and payload["stored"]
    assert not user_tree.exists()


def test_disk_purge_json_refusal_carries_the_reason(fake_home, capsys):
    """Sem as duas flags, a recusa sai como objeto no stdout — código 2 (falta confirmar)."""
    code = main(["disk", "purge", "1700000000-deadbeef", "--json"])

    captured = capsys.readouterr()
    assert code == cli.EXIT_NEEDS_CONFIRM
    payload = json.loads(captured.out)
    assert payload["acao"] == "purge" and payload["ok"] is False
    assert payload["exit"] == cli.EXIT_NEEDS_CONFIRM and payload["outcome"] == "recusa"
    assert "exige --confirmar" in payload["reason"]
    assert payload["reason"] in captured.err


def test_list_shows_quarantine_entries(fake_home, user_tree, capsys):
    main(["disk", "quarantine", str(user_tree), "--confirmar"])
    capsys.readouterr()

    code = main(["disk", "list"])

    out = capsys.readouterr().out
    assert code == 0
    assert "projeto-antigo" in out
    assert "2,0 KB" in out


def test_list_json_carries_the_entries_and_their_observed_size(fake_home, user_tree,
                                                               capsys):
    main(["disk", "quarantine", str(user_tree), "--confirmar"])
    capsys.readouterr()

    code = main(["disk", "list", "--json"])

    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True and payload["outcome"] == "sucesso"
    assert payload["entries"][0]["original"] == str(user_tree)
    assert payload["entries"][0]["observed_bytes"] == 2048
    assert payload["entries"][0]["state"] == "stored"
    assert "quarentena" not in captured.out, "JSON é uma linha, sem prosa"


def test_list_json_refuses_a_corrupt_manifest_instead_of_an_empty_list(fake_home,
                                                                       capsys):
    from folego import cli
    q = Quarantine(allowed_roots=[fake_home])
    q.root.mkdir(parents=True)
    q.manifest_path.write_text("lixo{")

    code = main(["disk", "list", "--json"])

    captured = capsys.readouterr()
    assert code == cli.EXIT_REFUSED
    payload = json.loads(captured.out)
    assert payload["ok"] is False and payload["outcome"] == "recusa"
    assert "inconsistente" in payload["reason"]
    assert "quarentena vazia" not in captured.out


def _journal_records(fake_home) -> list:
    path = fake_home / ".local" / "state" / "folego" / "operations.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_confirmed_quarantine_is_journaled_intent_before_result(fake_home, user_tree,
                                                                  capsys):
    code = main(["disk", "quarantine", str(user_tree), "--confirmar"])
    assert code == 0

    records = _journal_records(fake_home)
    assert [r["kind"] for r in records] == ["intent", "result"]
    assert records[0]["plan"]["action"] == "disk.quarantine"
    assert records[0]["plan"]["target"]["kind"] == "path"
    assert records[1]["result"]["outcome"] == "sucesso"
    assert records[1]["result"]["effects"]["bytes"] == 2048


def test_a_refused_quarantine_is_journaled_as_recusa(fake_home, capsys):
    code = main(["disk", "quarantine", "/mnt/sdcard/.cache", "--confirmar"])

    assert code == 1
    records = _journal_records(fake_home)
    assert [r["kind"] for r in records] == ["intent", "result"]
    assert records[1]["result"]["outcome"] == "recusa"
    assert records[1]["result"]["reason"].startswith("refused:")


def test_an_unconfirmed_quarantine_never_touches_the_journal(fake_home, user_tree,
                                                             capsys):
    code = main(["disk", "quarantine", str(user_tree)])

    assert code == 2
    assert _journal_records(fake_home) == []
    assert user_tree.exists()


def test_a_corrupt_journal_blocks_the_quarantine_before_any_move(fake_home, user_tree,
                                                                 capsys):
    from folego import cli

    journal = fake_home / ".local" / "state" / "folego" / "operations.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text("lixo\n", encoding="utf-8")

    code = main(["disk", "quarantine", str(user_tree), "--confirmar"])

    assert code == cli.EXIT_REFUSED
    assert "diário" in capsys.readouterr().err
    assert user_tree.exists(), "sem intenção registrada, nada pode ser movido"
    assert journal.read_text(encoding="utf-8") == "lixo\n"


def test_a_confirmed_restore_is_journaled(fake_home, user_tree, capsys):
    main(["disk", "quarantine", str(user_tree), "--confirmar"])
    capsys.readouterr()
    entry_id = next(iter(Quarantine(allowed_roots=[fake_home]).entries()))

    assert main(["disk", "restore", entry_id, "--confirmar"]) == 0
    records = _journal_records(fake_home)
    assert records[-2]["plan"]["action"] == "disk.restore"
    assert records[-2]["plan"]["target"]["key"] == entry_id
    assert records[-1]["result"]["outcome"] == "sucesso"
    assert records[-1]["result"]["effects"]["state"] == "restored"


def test_a_confirmed_purge_is_journaled(fake_home, user_tree, capsys):
    main(["disk", "quarantine", str(user_tree), "--confirmar"])
    capsys.readouterr()
    entry_id = next(iter(Quarantine(allowed_roots=[fake_home]).entries()))

    assert main(["disk", "purge", entry_id, "--confirmar", "--irreversivel"]) == 0
    records = _journal_records(fake_home)
    assert records[-2]["plan"]["action"] == "disk.purge"
    assert records[-1]["result"]["outcome"] == "sucesso"
    assert not user_tree.exists()


def _make_repair_pending(q, state="planned"):
    raw = json.loads(q.manifest_path.read_text())
    raw["entries"][0]["state"] = state
    q.manifest_path.write_text(json.dumps(raw))
    return raw["entries"][0]["entry_id"]


def test_list_repairs_an_interrupted_move_and_journals_it(fake_home, user_tree, capsys):
    main(["disk", "quarantine", str(user_tree), "--confirmar"])
    capsys.readouterr()
    q = Quarantine(allowed_roots=[fake_home])
    entry_id = _make_repair_pending(q)

    code = main(["disk", "list"])

    out = capsys.readouterr().out
    assert code == 0
    assert "stored" in out
    assert Quarantine(allowed_roots=[fake_home]).entries()[entry_id].state == "stored"
    records = _journal_records(fake_home)
    assert records[-2]["kind"] == "intent"
    assert records[-2]["plan"]["action"] == "disk.reconcile"
    assert records[-1]["result"]["outcome"] == "sucesso"
    assert records[-1]["result"]["effects"]["repaired"] == [entry_id]


def test_list_refuses_a_corrupt_manifest_instead_of_pretending_empty(fake_home, capsys):
    from folego import cli

    q = Quarantine(allowed_roots=[fake_home])
    q.root.mkdir(parents=True)
    q.manifest_path.write_text("lixo{")

    code = main(["disk", "list"])

    captured = capsys.readouterr()
    assert code == cli.EXIT_REFUSED
    assert "inconsistente" in captured.err and "JSON ilegível" in captured.err
    assert "quarentena vazia" not in captured.out, "desconhecido não vira vazio"
    assert q.manifest_path.read_text() == "lixo{", "nada foi reescrito por cima"


def test_list_still_reads_when_the_journal_blocks_the_repair(fake_home, user_tree,
                                                             capsys):
    """Porta fechada impede o reparo, não a leitura: o aviso nomeia o bloqueio."""
    main(["disk", "quarantine", str(user_tree), "--confirmar"])
    capsys.readouterr()
    q = Quarantine(allowed_roots=[fake_home])
    _make_repair_pending(q)
    journal = fake_home / ".local" / "state" / "folego" / "operations.jsonl"
    journal.write_text("lixo\n", encoding="utf-8")

    code = main(["disk", "list"])

    captured = capsys.readouterr()
    assert code == 0
    assert "reparo bloqueado" in captured.err and "diário" in captured.err
    assert "planned" in captured.out
    assert json.loads(q.manifest_path.read_text())["entries"][0]["state"] == "planned"
    assert journal.read_text(encoding="utf-8") == "lixo\n", "nada anexado por cima"


def test_list_warns_about_ambiguous_quarantine_entries(fake_home, user_tree, capsys):
    main(["disk", "quarantine", str(user_tree), "--confirmar"])
    capsys.readouterr()
    q = Quarantine(allowed_roots=[fake_home])
    entry_id = _make_repair_pending(q)
    shutil.rmtree(q.entries()[entry_id].stored)  # nem origem nem payload: manual
    before = _journal_records(fake_home)

    code = main(["disk", "list"])

    captured = capsys.readouterr()
    assert code == 0
    assert "decisão manual" in captured.err and entry_id in captured.err
    assert "planned" in captured.out
    assert _journal_records(fake_home) == before, "decisão manual não é operação"


def test_unknown_subcommand_exits_with_usage(fake_home, capsys):
    code = main(["disk", "explode"])

    assert code == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_refused_paths_are_reported_instead_of_crashing(fake_home, capsys):
    code = main(["disk", "quarantine", "/mnt/sdcard/.cache", "--confirmar"])

    assert code == 1
    err = capsys.readouterr().err
    assert "refused" in err
    assert not (fake_home / ".local" / "share" / "folego" / "quarantine").exists()


class _NoHolders:
    state = "complete"

    def pids_holding(self, path):
        return frozenset()


@pytest.fixture
def legacy_root(fake_home, tmp_path, monkeypatch):
    """A costura da rota legada: só a raiz `scratch` é "suportada" no teste."""
    from folego import cli

    scratch = tmp_path / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cli, "_tmp_legacy_roots", lambda: (str(scratch),))
    monkeypatch.setattr(cli, "_tmp_legacy_holders", lambda root: _NoHolders())
    monkeypatch.setattr(cli, "_tmp_legacy_mounts", lambda: ())
    return scratch


def test_tmp_dry_run_lists_expired_owned_entries(legacy_root, capsys):
    old = legacy_root / "pytest-of-misael"
    (old / "sub").mkdir(parents=True)
    (old / "sub" / "lixo.bin").write_bytes(b"a" * 1024)
    stale = time.time() - 10 * DAY
    os.utime(old / "sub" / "lixo.bin", (stale, stale))
    os.utime(old / "sub", (stale, stale))
    os.utime(old, (stale, stale))

    code = main(["disk", "tmp", "--raiz", str(legacy_root)])

    out = capsys.readouterr().out
    assert code == 0
    assert "pytest-of-misael" in out
    assert "1,0 KB" in out
    assert old.exists(), "dry-run must not delete"


def test_tmp_legacy_mutation_is_disabled_in_favour_of_tmpfs_release(legacy_root, capsys):
    """F1.1: a rota antiga apagava por `rmtree` sem holder, monte ou retenção."""
    from folego import cli

    old = legacy_root / "velho"
    old.mkdir(parents=True)
    (old / "f.bin").write_bytes(b"a" * 4096)
    stale = time.time() - 10 * DAY
    os.utime(old / "f.bin", (stale, stale))
    os.utime(old, (stale, stale))

    for flags in (["--confirmar"], ["--confirmar", "--irreversivel"],
                  ["--irreversivel"]):
        code = main(["disk", "tmp", "--raiz", str(legacy_root), *flags])
        err = capsys.readouterr().err
        assert code == cli.EXIT_REFUSED, flags
        assert "desativada" in err and "tmpfs release" in err
    assert old.exists() and (old / "f.bin").exists(), "nada foi alterado"


def test_tmp_legacy_refuses_a_root_outside_the_supported_list(fake_home, tmp_path, capsys):
    from folego import cli

    code = main(["disk", "tmp", "--raiz", str(tmp_path / "qualquer")])

    err = capsys.readouterr().err
    assert code == cli.EXIT_REFUSED
    assert "raiz suportada" in err and "tmpfs release" in err


def test_tmp_legacy_refuses_a_mount_inside_the_root(legacy_root, capsys):
    from folego import cli

    inner = str(legacy_root / "montado")
    cli._tmp_legacy_mounts = lambda: ((inner, "tmpfs"),)
    try:
        code = main(["disk", "tmp", "--raiz", str(legacy_root)])
    finally:
        pass
    err = capsys.readouterr().err
    assert code == cli.EXIT_REFUSED
    assert "monte" in err and inner in err


def test_tmp_legacy_names_items_held_open(legacy_root, capsys, monkeypatch):
    from folego import cli

    old = legacy_root / "em-uso"
    old.mkdir()
    (old / "f.bin").write_bytes(b"a" * 1024)
    stale = time.time() - 10 * DAY
    os.utime(old / "f.bin", (stale, stale))
    os.utime(old, (stale, stale))

    class Holders:
        state = "complete"

        def pids_holding(self, path):
            return frozenset({4242}) if path.endswith("em-uso") else frozenset()

    monkeypatch.setattr(cli, "_tmp_legacy_holders", lambda root: Holders())
    code = main(["disk", "tmp", "--raiz", str(legacy_root)])

    out = capsys.readouterr().out
    assert code == 0
    assert "em uso por pid 4242" in out
    assert old.exists()


def test_no_arguments_starts_the_gui(fake_home, monkeypatch, capsys):
    started = {}

    def fake_gui(argv=None):
        started["argv"] = argv
        return 0

    monkeypatch.setattr("folego.cli.run_gui", fake_gui)

    assert main([]) == 0
    assert started["argv"] == []


def test_cli_never_needs_a_display_for_disk_commands(fake_home, user_tree, monkeypatch):
    monkeypatch.setenv("DISPLAY", "")
    monkeypatch.setenv("WAYLAND_DISPLAY", "")
    assert main(["disk", "plan"]) == 0
