"""CLI for the disk hygiene milestone: dry-run plan, then explicit reversible reclaim."""
import json
import os
import time

import pytest

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


def test_list_shows_quarantine_entries(fake_home, user_tree, capsys):
    main(["disk", "quarantine", str(user_tree), "--confirmar"])
    capsys.readouterr()

    code = main(["disk", "list"])

    out = capsys.readouterr().out
    assert code == 0
    assert "projeto-antigo" in out
    assert "2,0 KB" in out


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


def test_tmp_dry_run_lists_expired_owned_entries(fake_home, tmp_path, capsys):
    scratch = tmp_path / "scratch"
    old = scratch / "pytest-of-misael"
    (old / "sub").mkdir(parents=True)
    (old / "sub" / "lixo.bin").write_bytes(b"a" * 1024)
    stale = time.time() - 10 * DAY
    os.utime(old / "sub" / "lixo.bin", (stale, stale))
    os.utime(old / "sub", (stale, stale))
    os.utime(old, (stale, stale))

    code = main(["disk", "tmp", "--raiz", str(scratch)])

    out = capsys.readouterr().out
    assert code == 0
    assert "pytest-of-misael" in out
    assert "1,0 KB" in out
    assert old.exists(), "dry-run must not delete"


def test_tmp_expire_requires_both_flags(fake_home, tmp_path, capsys):
    scratch = tmp_path / "scratch"
    old = scratch / "velho"
    old.mkdir(parents=True)
    (old / "f.bin").write_bytes(b"a" * 1024)
    stale = time.time() - 10 * DAY
    os.utime(old / "f.bin", (stale, stale))
    os.utime(old, (stale, stale))

    assert main(["disk", "tmp", "--raiz", str(scratch), "--confirmar"]) == 2
    assert "--irreversivel" in capsys.readouterr().err
    assert main(["disk", "tmp", "--raiz", str(scratch), "--irreversivel"]) == 2
    assert "--confirmar" in capsys.readouterr().err
    assert old.exists()


def test_tmp_expire_actually_frees_space(fake_home, tmp_path, capsys):
    scratch = tmp_path / "scratch"
    old = scratch / "velho"
    old.mkdir(parents=True)
    (old / "f.bin").write_bytes(b"a" * 4096)
    fresh = scratch / "sessao-em-uso"
    fresh.mkdir()
    stale = time.time() - 10 * DAY
    os.utime(old / "f.bin", (stale, stale))
    os.utime(old, (stale, stale))

    code = main(["disk", "tmp", "--raiz", str(scratch), "--confirmar", "--irreversivel"])

    out = capsys.readouterr().out
    assert code == 0
    assert "4,0 KB" in out
    assert not old.exists()
    assert fresh.exists()


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
