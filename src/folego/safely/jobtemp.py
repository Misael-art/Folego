"""Private persistent temporaries for children; never rewrite session profiles.

Directories remain after completion for inspection. No automatic cleanup or
adoption of legacy pytest fixtures is implied by creating a run directory.
"""
import json
import os
import stat
import tempfile
import shlex
from pathlib import Path

from ..core.tmpfs import read_mounts_checked
from .mounts import destination_verdict


def phasezero_tmpdir(env) -> str | None:
    home = Path(env.get("HOME", str(Path.home())))
    config = Path(env.get("XDG_CONFIG_HOME", str(home / ".config")))
    config = config / "environment.d/70-phasezero-agent-tmp.conf"
    try:
        for line in config.read_text().splitlines():
            if line.startswith("TMPDIR="):
                values = shlex.split(line.partition("=")[2])
                if len(values) == 1:
                    value = values[0].replace("${HOME}", str(home)).replace("$HOME", str(home))
                    if "$" not in value and Path(value).is_absolute():
                        return value
    except (OSError, ValueError):
        pass
    return None


def prevention_status(env=None) -> dict:
    env = os.environ if env is None else env
    configured = phasezero_tmpdir(env)
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    inherited = env.get("TMPDIR", "")
    old_environment = inherited == runtime or inherited.startswith(runtime.rstrip("/") + "/")
    return {"phasezero_configured_tmpdir": configured,
            "inherited_tmpdir": inherited, "inherited_runtime_tmpdir": old_environment,
            "message": ("novos filhos protegidos; este processo ainda herdou temporários no runtime; "
                        "processos antigos não foram alterados" if old_environment else
                        "novos filhos usam temporários privados verificados; ambiente de outros processos desconhecido")}


def prepare_job_environment(env=None, *, root=None, mounts=None,
                            min_free_bytes=64 * 1024 * 1024, max_runs=256) -> dict:
    result = dict(os.environ if env is None else env)
    if mounts is None:
        mounts, error = read_mounts_checked()
        if error:
            raise OSError(f"temporários: montagens desconhecidas: {error}")
    # Respect an existing PhaseZero root when its effective TMPDIR is already
    # persistent. Never read/source shell profiles or change XDG_RUNTIME_DIR.
    inherited = Path(result.get("TMPDIR", "/tmp"))
    if root is None:
        configured = phasezero_tmpdir(result)
        persistent = inherited.is_absolute() and destination_verdict(inherited, mounts=mounts).ok
        if not persistent and configured and destination_verdict(configured, mounts=mounts).ok:
            inherited = Path(configured)
        persistent = inherited.is_absolute() and destination_verdict(inherited, mounts=mounts).ok
        home = Path(result.get("HOME", str(Path.home())))
        data = Path(result.get("XDG_DATA_HOME", str(home / ".local/share")))
        root = (inherited / "folego-jobs" if persistent
                else data / "folego/job-tmp")
    root = Path(root)
    if not root.is_absolute() or ".." in root.parts:
        raise OSError("temporários: raiz precisa ser absoluta")
    for ancestor in (root, *root.parents):
        if ancestor.is_symlink():
            raise OSError("temporários: ancestral simbólico recusado")
    verdict = destination_verdict(root, mounts=mounts)
    if not verdict.ok:
        raise OSError(verdict.reason)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = root.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise OSError("temporários: raiz não é privada do UID")
    with os.scandir(root) as entries:
        if sum(1 for _ in entries) >= max_runs:
            raise OSError("temporários: limite de execuções retidas; revisão manual necessária")
    capacity = os.statvfs(root)
    if capacity.f_bavail * (capacity.f_frsize or capacity.f_bsize) < min_free_bytes:
        raise OSError("temporários: destino sem folga mínima")
    if capacity.f_files > 0 and capacity.f_favail < 16:
        raise OSError("temporários: destino sem inodes suficientes")
    run = Path(tempfile.mkdtemp(prefix="run-", dir=root))
    for name in ("general", "pytest-root"):
        (run / name).mkdir(mode=0o700)
    (run / "run.json").write_text(json.dumps({
        "schema": 1, "run_id": run.name, "uid": os.getuid(),
        "launcher_pid": os.getpid(), "state": "prepared",
        "inherited_tmpdir": result.get("TMPDIR"),
        "note": "nenhuma garantia de término/lease; remoção automática proibida",
    }))
    result.update(TMPDIR=str(run / "general"),
                  PYTEST_DEBUG_TEMPROOT=str(run / "pytest-root"),
                  FOLEGO_RUN_ID=run.name)
    return result
