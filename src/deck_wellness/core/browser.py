"""Which browser is holding its profile open, from /proc alone.

The tunings engine refuses to write a config file while the process that owns it
is running: the browser re-saves its preferences on exit and would silently undo
the change. The probe answers for one browser at a time so the refusal can name
what it saw.
"""
import os
from pathlib import Path

from .. import paths
from . import procfs
from .orphans import executable_of

EDGE_EXECUTABLES = ("msedge", "microsoft-edge")
# Helpers (msedge_crashpad_handler) are alive from boot and deliberately not
# listed: counting them would make the guard refuse forever.


def edge_running(proc_root=None, uid: int | None = None) -> str | None:
    """Name the Edge process that would re-save over us, or None when it is closed."""
    root = Path(proc_root) if proc_root else Path(paths.proc_root())
    own = os.getuid() if uid is None else uid
    for proc in procfs.list_processes(root):
        if proc.uid != own or proc.state == "Z":
            continue
        if _is_edge(proc):
            line = " ".join(proc.cmdline)[:70] or proc.comm
            return f"pid {proc.pid} · {proc.comm} · {line}"
    return None


def _is_edge(proc) -> bool:
    """The executable decides, because comm is a 15-character label a process can
    rewrite and a flag naming a browser does not make the process that browser."""
    exe = executable_of(proc).replace("\\", "/").lower()
    return exe.rsplit("/", 1)[-1] in EDGE_EXECUTABLES
