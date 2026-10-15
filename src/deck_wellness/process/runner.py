"""Run one action in a child process, with a deadline the parent can survive.

The parent communicates through argv and a JSON line on stdout, so the child can
be any module — including one that will get stuck in uninterruptible sleep on a
flaky mount. `Popen.wait(timeout)` plus SIGKILL is the whole trick: the tray
keeps polling and the user gets a verdict instead of a frozen window.
"""
import os
import signal
import subprocess
import threading
from dataclasses import dataclass

MUTEX = threading.Lock()


@dataclass(frozen=True)
class RunResult:
    argv: tuple[str, ...]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    killed: bool = False
    refused: str | None = None
    pid: int | None = None

    @property
    def ok(self) -> bool:
        return self.refused is None and not self.timed_out and self.exit_code == 0


def run_isolated(argv, *, timeout: float, lock: threading.Lock | None = MUTEX,
                 env: dict | None = None) -> RunResult:
    """Run argv to completion or kill it at the deadline; never hang the caller."""
    command = list(argv)
    if lock is not None and not lock.acquire(blocking=False):
        return RunResult(tuple(command), refused="já existe uma mutação em voo; "
                                                 "tente de novo quando ela terminar")
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env, start_new_session=True)
        try:
            out, err = proc.communicate(timeout=timeout)
            return RunResult(tuple(command), exit_code=proc.returncode, stdout=out,
                             stderr=err, pid=proc.pid)
        except subprocess.TimeoutExpired:
            out, err = _drain_and_kill(proc, timeout)
            return RunResult(tuple(command), exit_code=None, stdout=out, stderr=err,
                             timed_out=True, killed=True, pid=proc.pid)
        except OSError as exc:
            return RunResult(tuple(command), exit_code=None,
                             stderr=f"falha ao iniciar o processo: {exc}")
    finally:
        if lock is not None:
            lock.release()


def _drain_and_kill(proc, timeout: float) -> tuple[str, str]:
    """SIGKILL, then give the reaping a short window: a D-state child can outlive
    the kill, and the parent must return either way."""
    proc.kill()
    try:
        out, err = proc.communicate(timeout=min(max(timeout, 0.1), 2.0))
        return out, err
    except (subprocess.TimeoutExpired, OSError):
        _abandon(proc)
        return "", ""


def _abandon(proc) -> None:
    """Last resort for a child that will not die: it is in its own session, so
    the whole process group can be taken down without touching the tray."""
    try:
        os.killpg(proc.pid, int(signal.SIGKILL))
    except OSError:
        pass
