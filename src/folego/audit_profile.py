"""Persistent session profile and the boundary for background host effects."""
from contextlib import contextmanager
import fcntl
import os
import stat
import time

from . import paths
from .actions.accessibility import private_path, read_object, save_object

SUSPENDED = "Suspenso pelo Modo Auditor ou por preferência ilegível."


def status():
    try:
        value = read_object(paths.config_dir() / "audit-profile.json")
        if value is not None and type(value.get("enabled")) is not bool:
            raise ValueError("preferência de auditoria inválida")
    except (OSError, ValueError) as exc:
        return {"ok": False, "enabled": None, "reason": str(exc)}
    return {"ok": True, "enabled": value is not None and value["enabled"]}


def normal():
    return status()["enabled"] is False


HISTORY_FILE = "host-history.json"


def history_status():
    """Continuous host history outside the Auditor: off by default, a separate explicit choice."""
    try:
        value = read_object(paths.config_dir() / HISTORY_FILE)
        if value is not None and type(value.get("enabled")) is not bool:
            raise ValueError("preferência de histórico inválida")
    except (OSError, ValueError) as exc:
        return {"ok": False, "enabled": None, "reason": str(exc)}
    return {"ok": True, "enabled": value is not None and value["enabled"]}


def configure_history(enabled):
    if type(enabled) is not bool:
        raise ValueError("histórico contínuo exige escolha booleana")
    try:
        if history_status()["enabled"] != enabled:
            save_object(paths.config_dir() / HISTORY_FILE, {"schema": 1, "enabled": enabled})
    except (OSError, ValueError) as exc:
        return {**history_status(), "ok": False, "reason": str(exc)}
    return history_status()


def records():
    """Host history is written in the Auditor, or in the normal profile when continuous history is on.

    Recording only observes; effects stay governed by normal()/normal_effects()."""
    return status()["enabled"] is True or history_status()["enabled"] is True


@contextmanager
def _lock(*, exclusive):
    path = paths.state_dir() / "audit-profile.lock"
    private_path(path, create=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError("trava do Modo Auditor não é privada")
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(fd, mode | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError("Há uma operação em andamento. Tente mudar o perfil novamente quando terminar.")
                time.sleep(.02)
        yield
    finally:
        os.close(fd)


@contextmanager
def normal_effects():
    """Hold the profile stable from the final decision through the effect."""
    if not normal():
        yield False
        return
    with _lock(exclusive=False):
        yield normal()


def configure(enabled):
    if type(enabled) is not bool:
        raise ValueError("perfil de auditoria exige escolha booleana")
    try:
        with _lock(exclusive=True):
            current = status()
            if current["ok"] and current["enabled"] != enabled:
                save_object(paths.config_dir() / "audit-profile.json",
                            {"schema": 1, "enabled": enabled})
            return status()
    except (OSError, ValueError) as exc:
        return {**status(), "ok": False, "reason": str(exc)}
