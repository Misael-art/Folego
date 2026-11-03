"""Optional gated launcher for apps adopting the existing input ownership protocol."""
import os
from pathlib import Path
import subprocess
import sys
import time

from .accessibility import publish_lease

GATE = """import os,sys
fd=int(sys.argv[1])
ready=os.read(fd,1)
os.close(fd)
if ready != b'1': sys.exit(97)
os.execvpe(sys.argv[2],sys.argv[2:],os.environ)
"""


class LeaseRunUnknown(RuntimeError):
    """The application may still run; ownership is deliberately preserved."""


def _members(marker, session):
    pids = []
    deadline = time.monotonic() + 2
    for index, path in enumerate(Path("/proc").iterdir()):
        if index > 8192 or time.monotonic() >= deadline:
            raise ValueError("inventário de filhos incompleto; lease preservado")
        if not path.name.isdigit(): continue
        try:
            if path.stat().st_uid != os.getuid(): continue
            fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
            if fields[0] == "Z": continue
            with (path / "environ").open("rb") as stream: raw = stream.read(131073)
            if len(raw) > 131072: raise ValueError("inventário de ambiente excede orçamento")
            if int(fields[3]) == session or marker in raw.split(b"\0"):
                pids.append(int(path.name))
                if len(pids) > 64: raise ValueError("filhos excedem orçamento; lease preservado")
        except (FileNotFoundError, ProcessLookupError):
            continue
    return pids


def run(provider, argv):
    if not argv or len(argv) > 128:
        raise ValueError("comando obrigatório e limitado a 128 argumentos")
    first = publish_lease(provider, os.getpid(), "using", completion_required=True)
    marker = ("FOLEGO_INPUT_LEASE_ID=" + first["lease_id"]).encode()
    read_fd, write_fd = os.pipe()
    child = None
    opened = False
    try:
        child = subprocess.Popen([sys.executable, "-c", GATE, str(read_fd), *argv],
            pass_fds=(read_fd,), start_new_session=True,
            env={**os.environ, "FOLEGO_INPUT_LEASE_ID": first["lease_id"]})
        os.close(read_fd)
        read_fd = None
        # Durable child identity precedes the gate that allows its first effect.
        publish_lease(provider, os.getpid(), "using", child_pids=[child.pid], completion_required=True)
        os.write(write_fd, b"1")
        opened = True
        os.close(write_fd)
        write_fd = None
        while True:
            status = child.poll()
            children = _members(marker, child.pid)
            if not children and status is not None:
                publish_lease(provider, os.getpid(), "released", completion_required=True)
                return status
            publish_lease(provider, os.getpid(), "using", child_pids=children, completion_required=True)
            time.sleep(.5)
    except (OSError, ValueError, KeyboardInterrupt) as exc:
        if opened:
            raise LeaseRunUnknown("aplicação iniciada; propriedade/filhos incertos, lease preservado; "
                                  "nenhum processo foi encerrado") from exc
        raise
    finally:
        if read_fd is not None: os.close(read_fd)
        if write_fd is not None: os.close(write_fd)
        # Never kill an app or infer release when the launcher loses evidence.
        # A crash before the gate gives EOF; after it, the lease remains protected.
        if child is not None and child.poll() is not None:
            child.wait()
        elif child is not None and not opened:
            try: child.wait(timeout=2)
            except subprocess.TimeoutExpired: pass
