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
MODULE = "folego.actions.tunings.worker"


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
    from folego.ui.tune_jobs import TuneJobs

    layer = TuneJobs(env=sandbox, timeout_ms=4000)
    yield layer, []
    layer.shutdown()


def test_the_job_layer_serializes_disk_mutations_too():
    from folego.ui.tune_jobs import MUTATING
    assert "quarantine" in MUTATING and "purge" in MUTATING
    assert "recover" in MUTATING, "recover move/apaga clone e é mutação"
    assert "list" not in MUTATING and "plan" not in MUTATING


def test_real_child_uses_private_temporaries_with_old_parent_environment(qapp, sandbox, tmp_path, monkeypatch):
    from folego.ui.tune_jobs import TuneJobs
    from folego.safely import jobtemp

    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    sandbox["TMPDIR"] = str(runtime / "codex-desktop/tmp")
    sandbox["XDG_RUNTIME_DIR"] = str(runtime)
    monkeypatch.setattr(jobtemp, "read_mounts_checked", lambda: (
        (("/", "ext4"), (str(runtime), "tmpfs")), None))
    source = "import json,os; print(json.dumps({'ok':True,'tmp':os.environ['TMPDIR'],'pytest':os.environ['PYTEST_DEBUG_TEMPROOT'],'runtime':os.environ['XDG_RUNTIME_DIR']}))"
    jobs = TuneJobs(env=sandbox, argv_factory=lambda *args: [sys.executable, "-c", source])
    results = []
    try:
        jobs.run("status", "", done=results.append)
        assert pump(qapp, lambda: bool(results))
        payload = results[0]
        assert payload["ok"]
        assert payload["tmp"].startswith(sandbox["XDG_DATA_HOME"])
        assert payload["pytest"] != payload["tmp"]
        assert payload["runtime"] == str(runtime)
        assert Path(payload["tmp"]).is_dir()
        assert jobs.procs == []
    finally:
        jobs.shutdown()


def test_a_layer_that_shuts_down_leaves_no_child_running(qapp, sandbox):
    from folego.ui.tune_jobs import TuneJobs

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


def test_mutating_child_with_scalar_json_has_unknown_result(qapp, sandbox):
    from folego.ui.tune_jobs import TuneJobs
    answers = []
    layer = TuneJobs(env=sandbox, argv_factory=lambda *args:
                     [sys.executable, "-c", "print('null')"])
    try:
        layer.run("signal", "fixture", confirm=True, done=answers.append)
        assert pump(qapp, lambda: bool(answers))
        assert answers[0]["outcome"] == "desconhecido" and answers[0]["exit"] == 5
        assert layer.in_flight == 0 and not layer.procs
    finally:
        layer.shutdown()


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
    from folego.ui.tune_jobs import TuneJobs

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


def test_a_worker_that_cannot_start_finishes_once_and_frees_the_layer(qapp, sandbox,
                                                                      tmp_path):
    """R06: FailedToStart não emite finished; sem finalizar, a mutação fica em voo.

    O estado preso bloqueava toda mutação seguinte e o objeto do processo nunca
    era descartado.
    """
    from folego.ui.tune_jobs import TuneJobs

    answers = []
    layer = TuneJobs(env=sandbox, timeout_ms=1000,
                     argv_factory=lambda acao, tid, confirm:
                     [str(tmp_path / "nao-existe-mesmo")])
    try:
        layer.run("apply", "edge.startup_boost", confirm=True, done=answers.append)
        assert pump(qapp, lambda: len(answers) == 1), \
            "o worker que não inicia nunca finalizou"
        assert answers[0]["ok"] is False
        assert "iniciar" in answers[0]["reason"] or "no such" in answers[0]["reason"].lower()
        # o filho nem existiu: recusa é o desfecho honesto, não "desconhecido"
        assert answers[0]["outcome"] == "recusa" and answers[0]["exit"] == 1
        assert layer.in_flight == 0, "a mutação não pode ficar presa em voo"
        assert pump(qapp, lambda: layer.procs == []), \
            "o objeto concluído tem de sair da lista"
        # a segunda mutação não pode ser recusada por uma fantasma
        layer.run("revert", "edge.startup_boost", confirm=True, done=answers.append)
        assert pump(qapp, lambda: len(answers) == 2)
    finally:
        layer.shutdown()


def test_a_stalling_child_is_killed_and_reported(qapp, sandbox):
    from folego.ui.tune_jobs import TuneJobs

    stalled = []
    layer = TuneJobs(env=sandbox, timeout_ms=300,
                     argv_factory=lambda acao, tid, confirm:
                     [sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        layer.run("detect", "edge.startup_boost", done=stalled.append)
        assert pump(qapp, lambda: len(stalled) == 1), "um filho travado prendeu a janela"
        assert "não respondeu" in stalled[0]["reason"]
        # leitura estourada: nada foi tocado — recusa, não desconhecido
        assert stalled[0]["outcome"] == "recusa" and stalled[0]["exit"] == 1
        assert layer.in_flight == 0, "o filho morto não conta como mutação em voo"

        # a mesma trava numa mutação é outra história (entrega 7): tempo esgotado
        # não prova ausência de efeitos — o desfecho é desconhecido (5)
        layer.run("apply", "edge.startup_boost", confirm=True, done=stalled.append)
        assert pump(qapp, lambda: len(stalled) == 2), "a mutação travada não finalizou"
        assert stalled[1]["outcome"] == "desconhecido" and stalled[1]["exit"] == 5, \
            "tempo esgotado não é recusa: o filho pode ter começado o efeito"
        assert layer.in_flight == 0
    finally:
        layer.shutdown()


def test_only_one_mutation_is_in_flight_at_a_time(qapp, sandbox):
    from folego.ui.tune_jobs import TuneJobs

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
        assert answers[-1]["outcome"] == "recusa" and answers[-1]["exit"] == 1, \
            "recusar por concorrência é seguro: nada foi tocado"
        assert layer.in_flight == 1, "a recusa não abre um segundo filho"
    finally:
        layer.shutdown()
        pump(qapp, lambda: layer.in_flight == 0)


def test_a_tmpfs_release_blocks_the_next_mutation(qapp, sandbox):
    """Duas liberações simultâneas seriam duas cópias grandes ao mesmo tempo."""
    from folego.ui.tune_jobs import TuneJobs

    answers = []
    layer = TuneJobs(env=sandbox, timeout_ms=6000,
                     argv_factory=lambda acao, alvo, confirm:
                     [sys.executable, "-c", "import time; time.sleep(2)"])
    try:
        layer.run("release", "/tmp/qoder-cli-1000", confirm=True, done=answers.append)
        qapp.processEvents()
        assert layer.in_flight == 1
        layer.run("restore", "1700-abc", confirm=True, done=answers.append)
        assert answers[-1]["ok"] is False and "em voo" in answers[-1]["reason"]
        assert answers[-1]["outcome"] == "recusa" and answers[-1]["exit"] == 1, \
            "recusar por concorrência é seguro: nada foi tocado"
        assert layer.in_flight == 1, "a recusa não abre um segundo filho"
    finally:
        layer.shutdown()
        pump(qapp, lambda: layer.in_flight == 0)
