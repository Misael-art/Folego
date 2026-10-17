"""Ask the tuning worker through QProcess, so the window never waits for a write.

PySide's own async child-process machinery is the point: no Python-subclass
thread (cross-thread signals are unreliable on this interpreter), no
``waitForFinished`` blocking the event loop. A deadline timer kills the child and
the answer still lands as a payload, because "no answer" is itself a verdict the
user has to see.

Only one mutation runs at a time; the second request is refused here, in the
process that owns the mutex, exactly like the CLI does.
"""
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer
from shiboken6 import isValid

WORKER_MODULE = "folego.actions.tunings.worker"
MUTATING = ("apply", "revert", "release", "restore", "expire")
# .../src — where folego lives for this process. A child started from a
# .desktop file has no PYTHONPATH, and "-m folego.*" then dies on import.
PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])


def default_argv(acao: str, tuning_id: str, confirm: bool) -> list[str]:
    argv = [sys.executable, "-m", WORKER_MODULE, acao, tuning_id]
    if confirm:
        argv.append("--confirmar")
    return argv


class _Job:
    def __init__(self, acao: str, tuning_id: str, done):
        self.acao = acao
        self.tuning_id = tuning_id
        self.done = done
        self.timed_out = False
        self.abandoned = False
        self.start_error = ""
        self.mutating = acao in MUTATING


class TuneJobs:
    def __init__(self, *, env: dict[str, str] | None = None, timeout_ms: int = 15_000,
                 argv_factory=default_argv, parent=None):
        self._env = dict(env or {})
        self._timeout_ms = timeout_ms
        self._argv_factory = argv_factory
        self._parent = parent
        self._jobs: dict[QProcess, _Job] = {}
        self.in_flight = 0
        self.procs: list[QProcess] = []

    def run(self, acao: str, tuning_id: str, *, confirm: bool = False, done):
        if acao in MUTATING and self.in_flight:
            done({"acao": acao, "ok": False, "exit": 1, "tuning": tuning_id,
                  "reason": "já existe uma mutação em voo; tente de novo quando "
                            "ela terminar"})
            return
        proc = QProcess(self._parent)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        proc.setProcessEnvironment(self._environment())
        job = _Job(acao, tuning_id, done)
        self._jobs[proc] = job

        timer = QTimer(proc)
        timer.setSingleShot(True)
        timer.setInterval(self._timeout_ms)
        timer.timeout.connect(lambda: self._expire(proc))
        proc.finished.connect(lambda code, status: self._finish(proc))
        proc.errorOccurred.connect(lambda err: self._error(proc, err))

        argv = list(self._argv_factory(acao, tuning_id, confirm))
        self.procs.append(proc)
        if job.mutating:
            self.in_flight += 1
        timer.start()
        proc.start(argv[0], argv[1:])

    # ------------------------------------------------------------------ environment

    def _environment(self) -> QProcessEnvironment:
        """Pin PYTHONPATH to the package this process runs from: a launcher or a
        .desktop file carries no PYTHONPATH, and the child would die on import."""
        qenv = QProcessEnvironment.systemEnvironment()
        search = [PACKAGE_ROOT, str(self._env.get("PYTHONPATH") or ""),
                  qenv.value("PYTHONPATH", "")]
        env = {**self._env,
               "PYTHONPATH": os.pathsep.join(dict.fromkeys(p for p in search if p))}
        for key, value in env.items():
            qenv.insert(key, str(value))
        return qenv

    # ------------------------------------------------------------------ events

    def _expire(self, proc) -> None:
        job = self._jobs.get(proc)
        if job is None:
            return
        job.timed_out = True
        proc.kill()

    def _error(self, proc, error) -> None:
        job = self._jobs.get(proc)
        if job is None:
            return
        job.start_error = f"{error}"

    def _finish(self, proc) -> None:
        job = self._jobs.pop(proc, None)
        if job is None:
            return
        if job.mutating:
            self.in_flight -= 1
        if not isValid(proc):
            # the child outlived the object that was reading it (window closed
            # mid-write): an unreadable answer is reported, never guessed at
            job.done({"acao": job.acao, "tuning": job.tuning_id, "ok": False,
                      "exit": 1, "reason": "o filho terminou sem que a resposta "
                                           "pudesse ser lida"})
            return
        job.done(self._payload(proc, job))

    def shutdown(self) -> None:
        """Take down every child still running: none may outlive the window."""
        for proc in list(self._jobs):
            self._jobs[proc].abandoned = True
            try:
                if proc.state() != QProcess.ProcessState.NotRunning:
                    proc.kill()
                    proc.waitForFinished(300)
            except RuntimeError:
                self._jobs.pop(proc, None)

    def _payload(self, proc, job) -> dict:
        base = {"acao": job.acao, "tuning": job.tuning_id}
        if job.abandoned:
            return {**base, "ok": False, "exit": 1,
                    "reason": "a janela fechou antes da resposta do filho"}
        if job.timed_out:
            return {**base, "ok": False, "exit": 1,
                    "reason": f"o processo filho não respondeu em "
                              f"{self._timeout_ms} ms e foi encerrado "
                              f"(disco travado?)"}
        out = bytes(proc.readAllStandardOutput()).decode(errors="replace").strip()
        err = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
        if not out:
            reason = err or job.start_error or \
                f"o filho terminou sem resposta (código {proc.exitCode()})"
            return {**base, "ok": False, "exit": 1, "reason": reason}
        try:
            payload = json.loads(out.splitlines()[-1])
        except ValueError:
            return {**base, "ok": False, "exit": 1,
                    "reason": f"o filho respondeu algo que não é JSON: {out[:120]}"}
        return {**base, **payload}
