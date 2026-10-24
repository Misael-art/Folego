"""F3.5 CLI: opt-in sessions, UUID lifecycle and exclusions as local API."""
import json
import os

from folego import cli
from fixtures_proc import build_proc

PID = 4343


def _json(capsys):
    return json.loads(capsys.readouterr().out)


def _proc(fake_proc):
    build_proc(fake_proc, pids=[
        dict(pid=PID, comm="builder", ppid=1, pgid=900, session=901,
             uid=os.getuid(), starttime=808)])
    (fake_proc / "sys" / "kernel" / "random").mkdir(parents=True)
    (fake_proc / "sys" / "kernel" / "random" / "boot_id").write_text("boot-cli\n")
    return fake_proc


def test_session_start_is_explicit_and_returns_a_uuid(fake_home, fake_proc,
                                                      capsys):
    _proc(fake_proc)

    code = cli.main(["session", "start", "--pid", str(PID), "--project",
                     "Folego", "--manter-ativo", "--json"])

    payload = _json(capsys)
    assert code == 0 and payload["ok"] is True
    assert payload["session"]["pid"] == PID
    assert payload["session"]["project"] == "Folego"
    assert payload["session"]["keep_active"] is True
    assert len(payload["session"]["session_id"]) == 36
    assert (fake_home / ".local" / "state" / "folego" / "sessions.json").exists()


def test_session_heartbeat_disconnect_and_end_keep_the_process_untouched(
        fake_home, fake_proc, capsys):
    _proc(fake_proc)
    assert cli.main(["session", "start", "--pid", str(PID), "--json"]) == 0
    sid = _json(capsys)["session"]["session_id"]

    assert cli.main(["session", "heartbeat", sid, "--json"]) == 0
    assert _json(capsys)["session"]["state"] == "active"
    assert cli.main(["session", "disconnect", sid, "--json"]) == 0
    assert _json(capsys)["session"]["state"] == "disconnected"
    assert cli.main(["session", "end", sid, "--json"]) == 0
    assert _json(capsys)["session"]["state"] == "ended"
    assert cli.main(["session", "list", "--json"]) == 0
    assert _json(capsys)["sessions"][0]["pid"] == PID


def test_session_start_refuses_a_pid_that_is_not_in_the_read_view(
        fake_home, fake_proc, capsys):
    _proc(fake_proc)

    code = cli.main(["session", "start", "--pid", "999999", "--json"])

    payload = _json(capsys)
    assert code == 1 and payload["ok"] is False
    assert "não existe" in payload["reason"]


def test_a_missing_session_is_a_refusal(fake_home, capsys):
    code = cli.main(["session", "heartbeat", "00000000-0000-0000-0000-000000000000",
                     "--json"])

    payload = _json(capsys)
    assert code == 1 and payload["ok"] is False
    assert "não encontrada" in payload["reason"]


def test_exclusions_are_a_persisted_local_api(fake_home, capsys):
    assert cli.main(["exclusions", "add", "app", "builder",
                     "--manter-ativo", "--json"]) == 0
    added = _json(capsys)["exclusion"]
    assert added["kind"] == "app" and added["keep_active"] is True

    assert cli.main(["exclusions", "list", "--json"]) == 0
    assert _json(capsys)["exclusions"][0]["value"] == "builder"

    assert cli.main(["exclusions", "remove", added["exclusion_id"],
                     "--json"]) == 0
    assert _json(capsys)["removed"] == added["exclusion_id"]
    assert cli.main(["exclusions", "list", "--json"]) == 0
    assert _json(capsys)["exclusions"] == []


def test_a_keep_active_session_hides_an_otherwise_proven_orphan(
        fake_home, fake_proc, capsys):
    _proc(fake_proc)
    assert cli.main(["orphans", "--janela", "0"]) == 0
    assert "builder" in capsys.readouterr().out

    assert cli.main(["session", "start", "--pid", str(PID), "--project",
                     "Folego", "--manter-ativo", "--json"]) == 0
    capsys.readouterr()

    assert cli.main(["orphans", "--janela", "0"]) == 0
    out = capsys.readouterr().out
    assert "builder" not in out
    assert "sem órfão comprovado" in out


def test_session_run_launches_a_disposable_child_and_ends_the_session(
        fake_home, capsys):
    code = cli.main(["session", "run", "--project", "Folego", "--label",
                     "smoke", "--manter-ativo", "--", "/bin/sh", "-c", "exit 0"])

    assert code == 0
    assert "sessão " in capsys.readouterr().err
    assert cli.main(["session", "list", "--json"]) == 0
    sessions = _json(capsys)["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["state"] == "ended"
    assert sessions[0]["project"] == "Folego"
    assert sessions[0]["keep_active"] is True


def test_session_child_receives_explicit_disk_temporaries(fake_home, tmp_path, monkeypatch):
    import sys
    output = tmp_path / "child-env.json"
    runtime = tmp_path / "old-runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("TMPDIR", str(runtime / "codex-desktop/tmp"))
    # Synthetic table classifies only this disposable runtime as RAM.
    from folego.safely import jobtemp
    monkeypatch.setattr(jobtemp, "read_mounts_checked", lambda: (
        (("/", "ext4"), (str(runtime), "tmpfs")), None))
    source = ("import os,json,pathlib; pathlib.Path(" + repr(str(output)) +
              ").write_text(json.dumps(dict(os.environ)))")
    assert cli.main(["session", "run", "--project", "test", "--",
                     sys.executable, "-c", source]) == 0
    env = json.loads(output.read_text())
    assert env["TMPDIR"].startswith(str(fake_home))
    assert env["PYTEST_DEBUG_TEMPROOT"] != env["TMPDIR"]
    assert os.path.isdir(env["TMPDIR"])
