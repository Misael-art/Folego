"""F8 CLI migration: dry-run by default, origin preserved, no overwrite."""
import json

from folego import cli


def run(capsys, argv):
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, (json.loads(captured.out) if captured.out.strip() else None), captured


def test_no_legacy_state_is_a_successful_noop(fake_home, capsys):
    code, payload, _ = run(capsys, ["migrate", "--json"])
    assert code == cli.EXIT_OK
    assert payload["migrated"] is False
    assert payload["plan"]["entries"] == []


def test_dry_run_does_not_copy_and_confirm_preserves_the_original(fake_home, capsys):
    legacy = fake_home / ".config" / "deckwellness"
    legacy.mkdir(parents=True)
    (legacy / "prefs.json").write_text('{"old": true}')

    code, payload, _ = run(capsys, ["migrate", "--json"])
    assert code == cli.EXIT_OK and payload["migrated"] is False
    assert not (fake_home / ".config" / "folego").exists()

    code, payload, _ = run(capsys, ["migrate", "--confirmar", "--json"])
    assert code == cli.EXIT_OK and payload["migrated"] is True
    copied = fake_home / ".config" / "folego" / "prefs.json"
    assert copied.read_text() == '{"old": true}'
    assert (legacy / "prefs.json").exists(), "origem nunca é removida"


def test_a_symlink_blocks_the_whole_migration(fake_home, capsys):
    legacy = fake_home / ".config" / "deckwellness"
    legacy.mkdir(parents=True)
    (legacy / "real").write_text("x")
    (legacy / "link").symlink_to(legacy / "real")

    code, payload, _ = run(capsys, ["migrate", "--json"])
    assert code == cli.EXIT_REFUSED
    assert payload["ok"] is False and "link simbólico" in payload["reason"]
    assert not (fake_home / ".config" / "folego").exists()
