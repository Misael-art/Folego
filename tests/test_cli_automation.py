"""F6 CLI: grants are explicit, revocation is recorded, automatic needs proof."""
import json

from folego import cli


def run(capsys, argv):
    code = cli.main(argv)
    captured = capsys.readouterr()
    payload = json.loads(captured.out) if captured.out.strip() else None
    return code, payload, captured


def test_grants_start_empty_and_reading_creates_nothing(fake_home, capsys):
    code, payload, _ = run(capsys, ["grant", "list", "--json"])
    assert code == cli.EXIT_OK
    assert payload["grants"] == []
    assert not (fake_home / ".local" / "state" / "folego" / "grants.json").exists()


def test_a_grant_is_limited_listed_and_revoked(fake_home, capsys):
    code, payload, _ = run(capsys, [
        "grant", "add", "tmpfs.release", "--resource", '{"schema":1,"kind":"entry","key":"managed-test","detail":{}}', "--limit", "bytes=4096",
        "--ttl", "3600", "--json"])
    assert code == cli.EXIT_OK
    grant = payload["grant"]
    assert grant["action"] == "tmpfs.release" and grant["limits"] == {"bytes": 4096}

    code, payload, _ = run(capsys, ["grant", "list", "--json"])
    assert code == cli.EXIT_OK and len(payload["grants"]) == 1

    code, payload, _ = run(capsys, ["grant", "revoke", grant["grant_id"], "--json"])
    assert code == cli.EXIT_OK
    assert payload["grant"]["revoked_at"] is not None

    code, payload, _ = run(capsys, ["grant", "list", "--json"])
    assert payload["grants"][0]["revoked_at"] is not None


def test_a_malformed_limit_is_refused_without_writing(fake_home, capsys):
    code, payload, captured = run(capsys, [
        "grant", "add", "tmpfs.release", "--resource", '{"schema":1,"kind":"entry","key":"managed-test","detail":{}}', "--limit", "bytes=not-json", "--json"])
    assert code == cli.EXIT_REFUSED
    assert payload["ok"] is False and "não é JSON" in payload["reason"]
    assert "refused:" in captured.err
    assert not (fake_home / ".local" / "state" / "folego" / "grants.json").exists()


def test_default_status_is_manual(fake_home, capsys):
    code, payload, _ = run(capsys, ["automation", "status", "--json"])
    assert code == cli.EXIT_OK
    assert payload["mode"] == "manual" and payload["paused"] is False
    assert payload["grants_active"] == 0


def test_automatic_without_confirmation_or_grant_changes_nothing(fake_home, capsys):
    code, payload, _ = run(capsys, ["automation", "mode", "automatico", "--json"])
    assert code == cli.EXIT_NEEDS_CONFIRM
    assert "exige --confirmar" in payload["reason"]

    code, payload, _ = run(capsys, ["automation", "mode", "automatico",
                                    "--confirmar", "--json"])
    assert code == cli.EXIT_REFUSED
    assert "grant ativo" in payload["reason"]
    assert not (fake_home / ".local" / "state" / "folego" / "automation.json").exists()


def test_a_granted_mode_change_persists_and_pause_is_not_revoke(fake_home, capsys):
    code, _, _ = run(capsys, ["grant", "add", "tmpfs.release", "--resource", '{"schema":1,"kind":"entry","key":"managed-test","detail":{}}',
                              "--limit", "bytes=4096", "--json"])
    assert code == cli.EXIT_OK

    code, payload, _ = run(capsys, ["automation", "mode", "automatico",
                                    "--confirmar", "--json"])
    assert code == cli.EXIT_OK and payload["mode"] == "automatico"

    code, payload, _ = run(capsys, ["automation", "pause", "--json"])
    assert code == cli.EXIT_OK and payload["paused"] is True
    assert payload["grants_active"] == 1

    code, payload, _ = run(capsys, ["automation", "status", "--json"])
    assert payload["mode"] == "automatico" and payload["paused"] is True

    code, payload, _ = run(capsys, ["automation", "resume", "--json"])
    assert code == cli.EXIT_OK and payload["paused"] is False


def test_preset_does_not_touch_the_grant_file(fake_home, capsys):
    run(capsys, ["grant", "add", "tmpfs.release", "--resource", '{"schema":1,"kind":"entry","key":"managed-test","detail":{}}', "--limit", "bytes=4096",
                 "--json"])
    path = fake_home / ".local" / "state" / "folego" / "grants.json"
    before = path.read_bytes()

    code, payload, _ = run(capsys, ["automation", "preset", "foco", "--json"])

    assert code == cli.EXIT_OK and payload["preset"] == "foco"
    assert path.read_bytes() == before


def test_ecosystem_inventory_is_read_only_and_says_when_nothing_is_registered(fake_home,
                                                                             capsys):
    code, payload, _ = run(capsys, ["ecosystem", "--adapter", "projects",
                                    "--json"])
    assert code == cli.EXIT_OK
    assert payload["ok"] is True and payload["outcome"] == "sucesso"
    assert payload["adapters"][0]["name"] == "projects"
    assert payload["adapters"][0]["items"] == []
    assert "nenhum projeto" in payload["adapters"][0]["reason"]


def test_a_corrupt_config_is_unknown_not_manual(fake_home, capsys):
    path = fake_home / ".local" / "state" / "folego" / "automation.json"
    path.parent.mkdir(parents=True)
    path.write_text("lixo{")

    code, payload, _ = run(capsys, ["automation", "status", "--json"])
    assert code == cli.EXIT_UNKNOWN
    assert payload["ok"] is False and "ilegível" in payload["reason"]
