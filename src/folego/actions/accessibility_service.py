"""Optional user-session supervisor; never installs drivers or system services."""
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .. import paths
from ..orchestration.coordinator import CoordinatorBusy
from ..core.sessions import read_boot_id
from .accessibility import Supervisor, fresh, private_path, save_object

UNIT = "folego-accessibility.service"
MARKER = "# X-Folego-Managed=accessibility-v1"


def unit_text(executable=None, *, session_type=None):
    executable = executable or sys.executable
    session_type = session_type or os.environ.get("XDG_SESSION_TYPE", "")
    if session_type not in ("wayland", "x11"):
        raise ValueError("tipo de sessão gráfica não comprovado")
    if "\n" in executable or "\r" in executable:
        raise ValueError("executável inválido")
    quoted = '"' + executable.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
    return (MARKER + "\n[Unit]\nDescription=Fôlego accessibility supervision\n"
            "PartOf=graphical-session.target\nAfter=graphical-session.target\n"
            "[Service]\nType=simple\nExecStart=" + quoted + " -m folego accessibility watch\n"
            "Environment=XDG_SESSION_TYPE=" + session_type + "\nUMask=0077\nRestart=on-failure\nRestartSec=10\n"
            "[Install]\nWantedBy=graphical-session.target\n")


def install(*, confirmed=False, run=subprocess.run):
    if not confirmed:
        raise ValueError("instalar supervisor da sessão exige confirmação")
    binary = shutil.which("systemctl")
    if not binary or os.environ.get("XDG_SESSION_TYPE") not in ("wayland", "x11"):
        raise ValueError("supervisor de login requer systemd de usuário e sessão gráfica; use watch no terminal")
    path = paths.xdg_config_home() / "systemd/user" / UNIT
    private_path(path, create=True)
    if path.exists() and not path.read_text().startswith(MARKER + "\n"):
        raise ValueError("unit pessoal preservada")
    from ..safely.atomicfile import write_atomic
    write_atomic(path, unit_text().encode(), mode=0o600)
    for args in (("daemon-reload",), ("show", UNIT, "--property=FragmentPath", "--value"), ("enable", "--now", UNIT)):
        result = run([binary, "--user", *args], stdin=subprocess.DEVNULL,
                     capture_output=True, text=True, timeout=8, check=False)
        if result.returncode:
            raise ValueError("unit gravada, mas ativação não comprovada; consulte systemctl --user status " + UNIT)
        if args[0] == "show" and result.stdout.strip() != str(path):
            raise ValueError("serviço carregado de outro diretório; ativação recusada")
    return {"ok": True, "unit": UNIT, "path": str(path)}


def watch(*, supervisor=None, interval=10, cycles=None):
    supervisor = supervisor or Supervisor()
    lock = supervisor.store.root / "watch.lock"
    private_path(lock, create=True)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        from .deck_mapping import DeckMapping
        mapping = DeckMapping(supervisor.store, supervisor.coordinator) if isinstance(supervisor, Supervisor) else None
        count = 0
        while cycles is None or count < cycles:
            started = time.monotonic()
            previous_report = getattr(supervisor, "last_report", None)
            try:
                result = supervisor.tick()
            except Exception as exc:
                # State/source faults stop effects but keep an observable monitor alive.
                result = {"ok": False, "state": "unknown", "reason": str(exc)}
            overview = None
            try:
                from .accessibility import record_transition
                report = getattr(supervisor, "last_report", None)
                if report is not None and report is not previous_report:
                    if mapping is not None and supervisor.profile_guard is not None:
                        result["mapping"] = mapping.tick(report, supervisor.profile_guard)
                    if fresh(report):
                        overview = {key: report[key]
                                    for key in ("schema", "state", "mono", "boot_id")}
                        overview["clock"] = report.get("clock", "monotonic")
                        for key in ("blockers", "alerts"):
                            overview[key] = [value[:240] for value in report[key][:8]]
                    result["last_transition"] = record_transition(supervisor.store, report)
            except (OSError, ValueError, CoordinatorBusy, subprocess.SubprocessError) as exc:
                result["transition_error"] = str(exc)
            try:
                from ..audit_profile import normal_effects
                from ..safely.jobtemp import maintain_registered
                with normal_effects() as allowed:
                    if allowed:
                        result["temporary_retention"] = maintain_registered(cursor=count)
            except (OSError, ValueError) as exc:
                result["temporary_retention"] = {"archived": 0, "reason": str(exc)}
            save_object(supervisor.store.root / "watch-status.json",
                        {"schema": 1, "checked_at": time.time(), "result": result,
                         "overview": overview,
                         "owner": {"pid": os.getpid(), "boot_id": read_boot_id(),
                                   "start_ticks": int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19])},
                         "effects_scope": "enable-baseline-input-and-deck-profiles"})
            count += 1
            if cycles is None or count < cycles:
                remaining = max(1, interval - (time.monotonic() - started))
                until = time.monotonic() + remaining
                while mapping is not None and mapping.active and remaining > 2:
                    time.sleep(2)
                    try:
                        mapping.yield_to_game(supervisor.profile_guard)
                    except (OSError, ValueError, subprocess.SubprocessError, CoordinatorBusy):
                        pass  # The next resident cycle verifies the same unit and receipt.
                    remaining = max(0, until - time.monotonic())
                time.sleep(remaining)
        return {"ok": True, "cycles": count}
    finally:
        os.close(fd)
