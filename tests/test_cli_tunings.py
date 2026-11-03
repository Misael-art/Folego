"""CLI for M2: every tuning mutation is handed to a child process.

The tests spy on ``run_isolated`` rather than letting the real engine write in
process — that swap is the whole design point: if the CLI ever calls the engine
directly, a stuck write freezes the terminal too. The payloads the spy returns
are the worker's own JSON, so the printing is tested against the real shape.
Refusals and dry-run hints go to stderr, as everywhere else in this CLI: stdout
has to stay parseable for ``--json``.
"""
import json
import sys

import pytest

from folego.actions.tunings.registry import TUNINGS
from folego.cli import main
from folego.process.runner import RunResult

WORKER = "folego.actions.tunings.worker"


def detect_payload(tuning, **over):
    payload = {"acao": "detect", "ok": True, "exit": 0,
               "exists": True, "present": True, "current": True,
               "desired": False, "change_needed": True, "error": None,
               "file": f"/home/u/.config/microsoft-edge/{tuning.id}", "key": tuning.key,
               "label": tuning.label, "why": tuning.why}
    payload.update(over)
    return payload


def a_run(payload, exit_code=None):
    return RunResult(argv=(), exit_code=exit_code if exit_code is not None else payload["exit"],
                     stdout=json.dumps(payload, ensure_ascii=False) + "\n")


@pytest.fixture
def spy(monkeypatch):
    """Stands in for the child: records argv, answers with a canned payload."""
    calls = []
    box = {"answers": []}

    def fake_run_isolated(argv, *, timeout, **kw):
        calls.append((list(argv), timeout))
        answer = box["answers"].pop(0) if box["answers"] else None
        return answer if not isinstance(answer, RunResult) else answer

    monkeypatch.setattr("folego.cli.run_isolated", fake_run_isolated)
    spy.calls, spy.box = calls, box
    return spy


def argv_of(*action_and_id, confirmar=False):
    argv = [sys.executable, "-m", WORKER, *action_and_id]
    if confirmar:
        argv.append("--confirmar")
    return argv


# ------------------------------------------------------------------------ status

def test_status_asks_the_child_about_every_known_tuning(spy, fake_home, capsys):
    for tuning in TUNINGS:
        spy.box["answers"].append(a_run(detect_payload(tuning)))

    code = main(["tune", "status"])

    out = capsys.readouterr().out
    assert code == 0
    assert [call[0] for call in spy.calls] == [argv_of("detect", t.id) for t in TUNINGS]
    for tuning in TUNINGS:
        assert tuning.label in out


def test_status_calls_an_absent_key_the_browsers_own_default(spy, fake_home, capsys):
    tuning = TUNINGS[0]
    spy.box["answers"].extend([
        a_run(detect_payload(tuning, present=False, current=None)),
        a_run(detect_payload(TUNINGS[1], present=False, current=None)),
    ])

    main(["tune", "status"])

    out = capsys.readouterr().out
    assert "padrão do navegador" in out
    assert tuning.key in out


def test_status_says_when_an_adjustment_is_already_economical(spy, fake_home, capsys):
    spy.box["answers"].extend([
        a_run(detect_payload(TUNINGS[0], current=False, change_needed=False)),
        a_run(detect_payload(TUNINGS[1], current=False, change_needed=False)),
    ])

    main(["tune", "status"])

    out = capsys.readouterr().out
    assert out.count("desligado") >= 2


def test_status_reports_a_missing_file_instead_of_inventing_one(spy, fake_home, capsys):
    spy.box["answers"].extend([
        a_run(detect_payload(TUNINGS[0], exists=False, present=False, error="não existe")),
        a_run(detect_payload(TUNINGS[1], exists=False, present=False, error="não existe")),
    ])

    main(["tune", "status"])

    out = capsys.readouterr().out
    assert "não existe" in out


def test_status_survives_a_child_that_never_answers(spy, fake_home, capsys):
    timed_out = RunResult(argv=(), timed_out=True, killed=True)
    spy.box["answers"].extend([timed_out, a_run(detect_payload(TUNINGS[1]))])

    code = main(["tune", "status"])

    out = capsys.readouterr().out
    assert code == 1, "um filho que não respondeu não pode virar sucesso"
    assert "não respondeu" in out


def test_status_has_a_machine_readable_form(spy, fake_home, capsys):
    for tuning in TUNINGS:
        spy.box["answers"].append(a_run(detect_payload(tuning)))

    code = main(["tune", "status", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [item["id"] for item in payload["tunings"]] == [t.id for t in TUNINGS]
    assert payload["tunings"][0]["state"] == "ligado"


# ------------------------------------------------------------------- apply/revert

def test_apply_without_the_flag_is_a_dry_run_the_child_itself_refuses(
        spy, fake_home, capsys):
    tuning = TUNINGS[0]
    refused = a_run({"acao": "apply", "ok": False, "exit": 2, "backup_id": None,
                     "sha": None, "reason": "recusado: aplicar um tuning exige "
                                            "confirmação explícita", "file": "x"}, 2)
    spy.box["answers"].append(refused)

    code = main(["tune", "apply", tuning.id])

    err = capsys.readouterr().err
    assert code == 2
    assert spy.calls[0][0] == argv_of("apply", tuning.id)
    assert "dry-run" in err and "--confirmar" in err


def test_apply_confirmed_lands_in_the_child_and_reports_its_verdict(
        spy, fake_home, capsys):
    tuning = TUNINGS[0]
    applied = a_run({"acao": "apply", "ok": True, "exit": 0, "changed": True,
                     "reason": None, "sha": "abc123", "backup_id": "tunings.x/1-2",
                     "file": "/home/u/.config/microsoft-edge/Default/Preferences",
                     "plan": {"before_sha": "old", "after_sha": "abc123", "blocked": None}})
    spy.box["answers"].append(applied)

    code = main(["tune", "apply", tuning.id, "--confirmar"])

    out = capsys.readouterr().out
    assert code == 0
    assert spy.calls[0][0] == argv_of("apply", tuning.id, confirmar=True)
    assert "aplicado" in out and "abc123" in out and "backup" in out


def test_apply_names_the_browser_when_the_guard_refuses(spy, fake_home, capsys):
    tuning = TUNINGS[0]
    spy.box["answers"].append(a_run({"acao": "apply", "ok": False, "exit": 1,
                                     "reason": "recusado: o Microsoft Edge está aberto "
                                               "(pid 4321)", "sha": None,
                                     "backup_id": None, "file": "x",
                                     "plan": {"before_sha": None, "after_sha": None,
                                              "blocked": None}}, 1))

    code = main(["tune", "apply", tuning.id, "--confirmar"])

    err = capsys.readouterr().err
    assert code == 1
    assert "Edge está aberto" in err and "4321" in err


def test_revert_confirmed_asks_the_child_to_restore(spy, fake_home, capsys):
    tuning = TUNINGS[0]
    spy.box["answers"].append(a_run({"acao": "revert", "ok": True, "exit": 0,
                                     "reason": None, "sha": "deadbeef",
                                     "backup_id": "tunings.x/1-2", "file": "x"}))

    code = main(["tune", "revert", tuning.id, "--confirmar"])

    out = capsys.readouterr().out
    assert code == 0
    assert spy.calls[0][0] == argv_of("revert", tuning.id, confirmar=True)
    assert "restaurado" in out and "deadbeef" in out


def test_revert_without_the_flag_refuses_before_the_child(spy, fake_home, capsys):
    """R18: a recusa é local — nenhum filho chega a ser acionado sem confirmação."""
    tuning = TUNINGS[0]

    code = main(["tune", "revert", tuning.id])

    err = capsys.readouterr().err
    assert code == 2
    assert spy.calls == [], "sem --confirmar não se aciona o worker"
    assert "--confirmar" in err and "nada foi alterado" in err


def test_an_unknown_tuning_id_is_answered_with_the_ones_that_exist(
        spy, fake_home, capsys):
    spy.box["answers"].append(a_run({"acao": "apply", "ok": False, "exit": 1,
                                     "reason": "tuning desconhecido: edge.nada",
                                     "conhecidos": [t.id for t in TUNINGS]}, 1))

    code = main(["tune", "apply", "edge.nada", "--confirmar"])

    err = capsys.readouterr().err
    assert code == 1
    assert "edge.nada" in err
    assert all(t.id in err for t in TUNINGS)
