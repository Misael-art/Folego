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
MUTATING = ("apply", "revert", "release", "restore", "expire", "recover",
            "quarantine", "quarantine-reviewed", "purge", "signal", "runtime-size",
            "accessibility-repair", "accessibility-enable", "accessibility-disable",
            "accessibility-capture", "accessibility-rearm", "accessibility-install",
            "startup-enable", "startup-disable", "startup-sync")
MUTATING = (*MUTATING, "review-execute", "review-cancel", "review-reconcile", "jobs-retain")
MUTATING = (*MUTATING, "accessibility-activate", "accessibility-save-profile")
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
            done({"acao": acao, "ok": False, "exit": 1, "outcome": "recusa",
                  "tuning": tuning_id,
                  "reason": "já existe uma mutação em voo; tente de novo quando "
                            "ela terminar"})
            return
        try:
            environment = self._environment()
        except (OSError, ValueError) as exc:
            done({"acao": acao, "tuning": tuning_id, "ok": False,
                  "exit": 1, "outcome": "recusa",
                  "reason": f"temporários do filho não preparados: {exc}"})
            return
        proc = QProcess(self._parent)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        proc.setProcessEnvironment(environment)
        job = _Job(acao, tuning_id, done)
        job.manifest = environment.value("FOLEGO_RUN_MANIFEST")
        job.pid = None
        self._jobs[proc] = job

        timer = QTimer(proc)
        timer.setSingleShot(True)
        timer.setInterval(self._timeout_ms)
        timer.timeout.connect(lambda: self._expire(proc))
        proc.finished.connect(lambda code, status: self._finish(proc))
        proc.errorOccurred.connect(lambda err: self._error(proc, err))
        proc.started.connect(lambda: setattr(job, "pid", int(proc.processId())))

        if acao.startswith("review-"):
            argv = [sys.executable, "-m", "folego", "review", acao.removeprefix("review-"), "--json"]
            if acao == "review-plan": argv.extend(["--command", tuning_id])
            elif acao == "review-execute": argv.extend(["--plan", tuning_id])
            elif acao in ("review-reconcile", "review-cancel"): argv.append(tuning_id)
            if confirm:
                argv.append("--confirmar")
                if acao == "review-execute": argv.append("--irreversivel")
        else:
            argv = list(self._argv_factory(acao, tuning_id, confirm))
        argv = [sys.executable, "-m", "folego.process.job_child", job.manifest, "--", *argv]
        self.procs.append(proc)
        if job.mutating:
            self.in_flight += 1
        timer.start()
        proc.start(argv[0], argv[1:])

    def review_and_run(self, action, target, *, title, text, confirm_fn, done, expected_scope=None):
        """Review in a child, confirm those bytes/targets, execute the same ID."""
        argv = self._argv_factory(action, target, False)
        if argv[1:3] == ["-m", WORKER_MODULE]:
            command = ["tune", action, target]
        elif argv[1:3] == ["-m", "folego"]:
            command = argv[3:]
        else:
            done({"outcome": "recusa", "ok": False, "reason": "comando sem protocolo de revisão"})
            return
        def planned(payload):
            bundle = payload.get("review") if payload else None
            if not bundle:
                done(payload or {"outcome": "desconhecido", "reason": "plano ausente"})
                return
            from ..orchestration.models import ActionPlan
            try:
                plan = ActionPlan.from_dict(bundle["plan"])
            except (ValueError, KeyError, TypeError):
                done({"outcome": "recusa", "reason": "plano ilegível"})
                return
            summary = bundle.get("evidence", {}).get("summary", [])
            if expected_scope is not None:
                expected = sorted(json.dumps(row, sort_keys=True) for row in expected_scope)
                fields = set().union(*(row.keys() for row in expected_scope)) if expected_scope else set()
                actual = sorted(json.dumps({key: row.get(key) for key in fields}, sort_keys=True) for row in summary)
                if expected != actual:
                    self.run("review-cancel", plan.operation_id, confirm=True, done=lambda _: done(
                        {"outcome": "recusa", "ok": False, "reason": "alvos/tamanhos mudaram desde a lista; atualizar antes de confirmar"}))
                    return
            from datetime import datetime
            from ..actions.disk.planner import fmt_bytes
            rows = [" · " + row.get("source", row["key"]) +
                    (" · " + fmt_bytes(row["bytes"]) if "bytes" in row else "") for row in summary]
            validity = datetime.fromtimestamp(plan.expires_at).astimezone().strftime("%d/%m %H:%M:%S")
            detail = "\n\nAlvos da revisão atual:\n" + "\n".join(rows) + f"\n\nOperação {plan.operation_id}\nVálida até {validity}"
            if not confirm_fn(title, text + detail):
                self.run("review-cancel", plan.operation_id, confirm=True, done=done)
                return
            def completed(result):
                result = result or {}
                if result.get("operation_id") not in (None, plan.operation_id):
                    result = {"outcome": "desconhecido", "ok": False, "reason": "ID do filho difere da revisão; não repetir"}
                done({"acao": action, "changed": result.get("ok", False),
                      **result.get("effects", {}), **result, "operation_id": plan.operation_id})
            self.run("review-execute", json.dumps(bundle), confirm=True, done=completed)
        self.run("review-plan", json.dumps(command), done=planned)

    # ------------------------------------------------------------------ environment

    def _environment(self) -> QProcessEnvironment:
        """Pin PYTHONPATH to the package this process runs from: a launcher or a
        .desktop file carries no PYTHONPATH, and the child would die on import."""
        qenv = QProcessEnvironment.systemEnvironment()
        from ..safely.jobtemp import prepare_job_environment
        child_env = {key: qenv.value(key) for key in qenv.keys()}
        child_env.update(self._env)
        child_env = prepare_job_environment(child_env)
        search = [PACKAGE_ROOT, str(self._env.get("PYTHONPATH") or ""),
                  qenv.value("PYTHONPATH", "")]
        env = {**child_env,
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
        job.start_error = f"não foi possível iniciar o filho: {error}"
        if error == QProcess.ProcessError.FailedToStart:
            # R06: FailedToStart não emite finished; sem finalizar aqui a mutação
            # ficava em voo para sempre e o processo nunca saía da lista.
            self._finish(proc)

    def _finish(self, proc) -> None:
        job = self._jobs.pop(proc, None)
        if job is None:
            return
        if job.mutating:
            self.in_flight -= 1
        if isValid(proc):
            payload = self._payload(proc, job)
        else:
            # the child outlived the object that was reading it (window closed
            # mid-write): an unreadable answer is reported, never guessed at
            payload = {"acao": job.acao, "tuning": job.tuning_id, "ok": False,
                       "exit": 5 if job.mutating else 1,
                       "outcome": "desconhecido" if job.mutating else "recusa",
                       "reason": "o filho terminou sem que a resposta "
                                            "pudesse ser lida"}
        self._forget(proc)
        try:
            from ..safely.jobtemp import finish_job
            finish_job(job.manifest, job.pid, certain=(not job.timed_out and not job.abandoned
                       and payload.get("outcome") != "desconhecido"))
        except (OSError, ValueError):
            pass  # Missing/uncertain lifecycle remains protected, never deleted.
        if self._parent is None or isValid(self._parent):
            job.done(payload)

    def _forget(self, proc) -> None:
        try:
            self.procs.remove(proc)
        except ValueError:
            pass
        try:
            proc.deleteLater()
        except RuntimeError:
            pass

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

        def unknown_or_refused(reason: str) -> dict:
            """Sem resposta legível: mutação pode ter efeitos (desconhecido, 5);
            leitura não (recusa, 1) — o desfecho tem de ser o que se sabe."""
            if job.mutating:
                return {**base, "ok": False, "exit": 5, "outcome": "desconhecido",
                        "reason": reason}
            return {**base, "ok": False, "exit": 1, "outcome": "recusa",
                    "reason": reason}

        if job.abandoned:
            # a janela fechou antes da resposta: numa mutação o filho pode ter
            # começado (ou terminado) o efeito — "recusa" aqui seria mentira
            return unknown_or_refused("a janela fechou antes da resposta do filho")
        if job.timed_out:
            return unknown_or_refused(f"o processo filho não respondeu em "
                                      f"{self._timeout_ms} ms e foi encerrado "
                                      f"(disco travado?)")
        out = bytes(proc.readAllStandardOutput()).decode(errors="replace").strip()
        err = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
        if not out:
            reason = err or job.start_error or \
                f"o filho terminou sem resposta (código {proc.exitCode()})"
            if job.start_error:
                # FailedToStart: o filho não existiu, nada foi feito
                return {**base, "ok": False, "exit": 1, "outcome": "recusa",
                        "reason": reason}
            return unknown_or_refused(reason)
        try:
            payload = json.loads(out.splitlines()[-1])
        except ValueError:
            return unknown_or_refused(
                f"o filho respondeu algo que não é JSON: {out[:120]}")
        if not isinstance(payload, dict):
            return unknown_or_refused("o filho respondeu JSON sem objeto de resultado")
        return {**base, **payload}
