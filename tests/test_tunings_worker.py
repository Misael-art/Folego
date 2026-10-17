"""M2 worker: the mutation runs in a child, and answers in one JSON line.

The whole point of the worker is that the tray never holds the write. These
tests drive it the way the app does — a real subprocess, a sandboxed HOME, a fake
/proc — so what they prove is the actual child's behaviour, not a function's.
The revert test is the plan's own acceptance bullet: byte-for-byte back.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODULE = "folego.actions.tunings.worker"


@pytest.fixture
def sandbox(tmp_path):
    from fixtures_proc import build_proc

    home = tmp_path / "home"
    edge = home / ".config" / "microsoft-edge"
    (edge / "Default").mkdir(parents=True)
    proc_root = tmp_path / "proc"
    build_proc(proc_root, pids=[])
    env = dict(os.environ,
               HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local" / "share"),
               XDG_STATE_HOME=str(home / ".local" / "state"),
               DECKWELLNESS_PROC_ROOT=str(proc_root),
               PYTHONPATH=str(REPO / "src"), QT_QPA_PLATFORM="offscreen")
    return {"home": home, "edge": edge, "env": env, "proc": proc_root}


def worker(sandbox, *args):
    return subprocess.run([sys.executable, "-m", MODULE, *args],
                          capture_output=True, text=True, env=sandbox["env"],
                          cwd=str(REPO), timeout=30)


def answer(sandbox, *args):
    run = worker(sandbox, *args)
    assert run.stdout.strip(), f"sem resposta: {run.stderr}"
    return json.loads(run.stdout.strip().splitlines()[-1]), run


def write_local_state(sandbox, doc):
    data = json.dumps(doc, separators=(",", ":")).encode()
    (sandbox["edge"] / "Local State").write_bytes(data)
    return data


# ----------------------------------------------------------------------- detect

def test_detect_answers_with_one_machine_readable_line(sandbox):
    write_local_state(sandbox, {"startup_boost": {"enabled": True}})

    payload, run = answer(sandbox, "detect", "edge.startup_boost")

    assert run.returncode == 0
    assert payload["acao"] == "detect"
    assert payload["present"] is True and payload["current"] is True
    assert payload["change_needed"] is True


def test_detect_names_an_unknown_tuning_instead_of_guessing(sandbox):
    payload, run = answer(sandbox, "detect", "edge.nada_disso")

    assert run.returncode == 1
    assert "desconhecido" in payload["reason"]


def test_detect_reports_a_missing_file_without_creating_it(sandbox):
    payload, run = answer(sandbox, "detect", "edge.startup_boost")

    assert run.returncode == 0
    assert payload["exists"] is False and "não existe" in payload["error"]
    assert not (sandbox["edge"] / "Local State").exists()


# ------------------------------------------------------------------------ apply

def test_apply_without_the_confirm_flag_writes_nothing(sandbox):
    original = write_local_state(sandbox, {"startup_boost": {"enabled": True}})

    payload, run = answer(sandbox, "apply", "edge.startup_boost")

    assert run.returncode == 2 and payload["ok"] is False
    assert "confirma" in payload["reason"]
    assert (sandbox["edge"] / "Local State").read_bytes() == original


def test_apply_through_the_worker_writes_the_planned_value(sandbox):
    write_local_state(sandbox, {"startup_boost": {"enabled": True, "x": "y"}})

    payload, run = answer(sandbox, "apply", "edge.startup_boost", "--confirmar")

    assert run.returncode == 0 and payload["ok"] is True
    doc = json.loads((sandbox["edge"] / "Local State").read_bytes())
    assert doc["startup_boost"] == {"enabled": False, "x": "y"}
    assert payload["sha"] == hashlib.sha256(
        (sandbox["edge"] / "Local State").read_bytes()).hexdigest()


def test_the_audit_line_lands_in_the_sandbox_state_dir(sandbox):
    write_local_state(sandbox, {"startup_boost": {"enabled": True}})

    answer(sandbox, "apply", "edge.startup_boost", "--confirmar")

    audit = sandbox["home"] / ".local" / "state" / "folego" / "audit.jsonl"
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert records[-1]["kind"] == "tuning.apply"
    assert records[-1]["action_id"] == "tunings.edge.startup_boost"
    assert records[-1]["outcome"] == "applied"


def test_revert_after_apply_restores_the_original_bytes_exactly(sandbox):
    original = write_local_state(sandbox, {"startup_boost": {"enabled": True, "x": "y"}})
    applied, _ = answer(sandbox, "apply", "edge.startup_boost", "--confirmar")

    payload, run = answer(sandbox, "revert", "edge.startup_boost")

    assert run.returncode == 0 and payload["ok"] is True
    path = sandbox["edge"] / "Local State"
    assert path.read_bytes() == original
    assert hashlib.sha256(path.read_bytes()).hexdigest() != applied["sha"]


def test_revert_without_any_backup_says_so(sandbox):
    write_local_state(sandbox, {"startup_boost": {"enabled": False}})

    payload, run = answer(sandbox, "revert", "edge.startup_boost")

    assert run.returncode == 1 and payload["ok"] is False
    assert "backup" in payload["reason"]


# ------------------------------------------------------------- the open-browser guard

def test_the_worker_refuses_while_an_edge_process_is_running(sandbox):
    from fixtures_proc import pid_dir

    original = write_local_state(sandbox, {"startup_boost": {"enabled": True}})
    pid_dir(sandbox["proc"], 4321, comm="msedge",
            cmdline=["/opt/microsoft/msedge/msedge", "--profile-directory=Default"])

    payload, run = answer(sandbox, "apply", "edge.startup_boost", "--confirmar")

    assert run.returncode == 1 and payload["ok"] is False
    assert "Edge está aberto" in payload["reason"] and "4321" in payload["reason"]
    assert (sandbox["edge"] / "Local State").read_bytes() == original
    assert json.loads(run.stdout)["backup_id"] is None, "recusa não cria backup"
