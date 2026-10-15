"""M3 job layer: the window asks a child, and never waits for it.

These tests drive the real QProcess against the real worker (and against a
stalling child for the timeout path), because the whole purpose of this module
is that the tray survives a child that will not answer. Spinning Qt's event loop
is how the answer arrives — no thread, no blocking call.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

REPO = Path(__file__).resolve().parent.parent
MODULE = "deck_wellness.actions.tunings.worker"


def pump(app, predicate, timeout_ms=4000):
    """Drain the event loop until the predicate holds (or the deadline passes)."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return False


@pytest.fixture
def sandbox(tmp_path):
    from fixtures_proc import build_proc

    home = tmp_path / "home"
    edge = home / ".config" / "microsoft-edge"
    (edge / "Default").mkdir(parents=True)
    (edge / "Local State").write_bytes(
        json.dumps({"startup_boost": {"enabled": True}}, separators=(",", ":")).encode())
    proc_root = tmp_path / "proc"
    build_proc(proc_root, pids=[])
    (home / ".local" / "state").mkdir(parents=True)
    return dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                XDG_DATA_HOME=str(home / ".local" / "share"),
                XDG_STATE_HOME=str(home / ".local" / "state"),
                DECKWELLNESS_PROC_ROOT=str(proc_root), PYTHONPATH=str(REPO / "src"),
                QT_QPA_PLATFORM="offscreen")


@pytest.fixture
def jobs(qapp, sandbox):
    from deck_wellness.ui.tune_jobs import TuneJobs

    layer = TuneJobs(env=sandbox, timeout_ms=4000)
    yield layer, []
    layer.shutdown()


def test_a_layer_that_shuts_down_leaves_no_child_running(qapp, sandbox):
    from deck_wellness.ui.tune_jobs import TuneJobs

    answers = []
    layer = TuneJobs(env=sandbox, timeout_ms=6000,
                     argv_factory=lambda acao, tid, confirm:
                     [sys.executable, "-c", "import time; time.sleep(60)"])
    layer.run("apply", "edge.startup_boost", confirm=True, done=answers.append)
    qapp.processEvents()
    assert layer.in_flight == 1

    layer.shutdown()
    pump(qapp, lambda: answers and layer.in_flight == 0)
    assert "a janela fechou antes da resposta" in answers[-1]["reason"]
    assert layer.in_flight == 0, "um filho morto não pode travar a próxima mutação"


def test_a_real_child_answers_with_its_own_json_line(qapp, jobs):
    layer, seen = jobs
    layer.run("detect", "edge.startup_boost", done=seen.append)

    assert pump(qapp, lambda: len(seen) == 1), "o filho nunca respondeu"
    payload = seen[0]
    assert payload["acao"] == "detect" and payload["current"] is True
    assert payload["change_needed"] is True


def test_the_confirm_flag_reaches_the_child_argv(qapp, jobs, sandbox):
    layer, seen = jobs
    layer.run("apply", "edge.startup_boost", confirm=True, done=seen.append)

    assert layer.procs[-1].arguments()[-1] == "--confirmar"
    assert pump(qapp, lambda: len(seen) == 1)
    assert seen[0]["ok"] is True
    local_state = Path(sandbox["HOME"]) / ".config" / "microsoft-edge" / "Local State"
    assert json.loads(local_state.read_bytes())["startup_boost"] == {"enabled": False}


def test_a_child_finds_the_package_without_a_pythonpath_in_the_environment(qapp, sandbox,
                                                                          monkeypatch):
    """Launched from a .desktop there is no PYTHONPATH at all: the layer has to
    tell the child where its own package lives, or every tab answers "no JSON"."""
    from deck_wellness.ui.tune_jobs import TuneJobs

    monkeypatch.delenv("PYTHONPATH", raising=False)
    env = {k: v for k, v in sandbox.items() if k != "PYTHONPATH"}
    answers = []
    layer = TuneJobs(env=env, timeout_ms=8000)
    try:
        layer.run("detect", "edge.startup_boost", done=answers.append)
        assert pump(qapp, lambda: len(answers) == 1), "o filho não respondeu"
        assert answers[0].get("current") is True, answers[0]
    finally:
        layer.shutdown()


def test_a_stalling_child_is_killed_and_reported(qapp, sandbox):
    from deck_wellness.ui.tune_jobs import TuneJobs

    stalled = []
    layer = TuneJobs(env=sandbox, timeout_ms=300,
                     argv_factory=lambda acao, tid, confirm:
                     [sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        layer.run("detect", "edge.startup_boost", done=stalled.append)
        assert pump(qapp, lambda: len(stalled) == 1), "um filho travado prendeu a janela"
        assert "não respondeu" in stalled[0]["reason"]
        assert layer.in_flight == 0, "o filho morto não conta como mutação em voo"
    finally:
        layer.shutdown()


def test_only_one_mutation_is_in_flight_at_a_time(qapp, sandbox):
    from deck_wellness.ui.tune_jobs import TuneJobs

    answers = []
    layer = TuneJobs(env=sandbox, timeout_ms=6000,
                     argv_factory=lambda acao, tid, confirm:
                     [sys.executable, "-c", "import time; time.sleep(2)"])
    try:
        layer.run("apply", "edge.startup_boost", confirm=True, done=answers.append)
        qapp.processEvents()
        assert layer.in_flight == 1

        layer.run("apply", "edge.background_mode", confirm=True, done=answers.append)
        assert answers[-1]["ok"] is False and "em voo" in answers[-1]["reason"]
        assert layer.in_flight == 1, "a recusa não abre um segundo filho"
    finally:
        layer.shutdown()
        pump(qapp, lambda: layer.in_flight == 0)
