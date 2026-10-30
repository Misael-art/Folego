"""Private persistent temporaries for children; never rewrite session profiles.

Completed owned runs can move to bounded persistent retention. Payloads and
legacy/unknown runs are preserved; no pytest fixture is adopted or deleted.
"""
import json
import os
import stat
import tempfile
import shlex
import fcntl
import time
import hashlib
from contextlib import contextmanager
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
    if root is None and result.get("FOLEGO_JOB_ROOT"):
        root = Path(result["FOLEGO_JOB_ROOT"])
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
    _register_root(root, result)
    with _root_lock(root):
        with os.scandir(root) as entries:
            count = 0
            for entry in entries:
                if entry.name not in (".retention.lock", ".retained"):
                    count += 1
                    if count >= max_runs:
                        raise OSError("temporários: limite de execuções retidas; revisão manual necessária")
        capacity = os.statvfs(root)
        if capacity.f_bavail * (capacity.f_frsize or capacity.f_bsize) < min_free_bytes:
            raise OSError("temporários: destino sem folga mínima")
        if capacity.f_files > 0 and capacity.f_favail < 16:
            raise OSError("temporários: destino sem inodes suficientes")
        run = Path(tempfile.mkdtemp(prefix="run-", dir=root))
        for name in ("general", "pytest-root"):
            (run / name).mkdir(mode=0o700)
        from ..actions.accessibility import save_object
        save_object(run / "run.json", {
            "schema": 2, "run_id": run.name, "uid": os.getuid(),
            "launcher_pid": os.getpid(), "state": "prepared", "child": None,
            "root_identity": [root.stat().st_dev, root.stat().st_ino],
            "run_identity": [run.stat().st_dev, run.stat().st_ino],
            "inherited_tmpdir": result.get("TMPDIR"),
            "note": "retido até encerramento certificado; legado e desconhecido são protegidos",
        })
    result.update(TMPDIR=str(run / "general"),
                  PYTEST_DEBUG_TEMPROOT=str(run / "pytest-root"),
                  FOLEGO_RUN_ID=run.name, FOLEGO_RUN_MANIFEST=str(run / "run.json"),
                  FOLEGO_JOB_ROOT=str(root))
    return result


@contextmanager
def _root_lock(root):
    path = root / ".retention.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OSError("trava de temporários não é privada")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def _manifest(path):
    from ..actions.accessibility import private_path
    private_path(path)
    info = path.stat()
    if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode) or info.st_size > 16384 or info.st_mode & 0o077:
        raise OSError("manifesto de temporários não é privado")
    value = json.loads(path.read_text())
    if (type(value.get("schema")) is not int or value["schema"] != 2
            or value.get("uid") != os.getuid() or value.get("run_id") != path.parent.name):
        raise OSError("manifesto legado/desconhecido; preservado")
    run, root = path.parent.stat(), path.parent.parent.stat()
    if (value.get("root_identity") != [root.st_dev, root.st_ino]
            or value.get("run_identity") != [run.st_dev, run.st_ino]
            or run.st_uid != os.getuid() or stat.S_IMODE(run.st_mode) != 0o700):
        raise OSError("identidade do temporário/raiz mudou; preservado")
    return value


def begin_job(path):
    from ..actions.accessibility import save_object
    from ..core.sessions import read_boot_id
    path = Path(path)
    value = _manifest(path)
    if value.get("state") != "prepared" or value.get("launcher_pid") != os.getppid():
        raise OSError("launcher/estado de temporários mudou")
    if os.getsid(0) != os.getpid():
        os.setsid()  # Only this freshly spawned job, before executing its command.
    fields = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
    value.update(state="running", child={"pid": os.getpid(), "start_ticks": int(fields[19]),
                                        "boot_id": read_boot_id()}, session=os.getsid(0))
    save_object(path, value)
    # Reclaim the *live* directory slots in this child, never on the Qt loop.
    try:
        with _root_lock(path.parent.parent):
            _archive_completed(path.parent.parent)
    except (OSError, ValueError):
        pass  # Uncertainty preserves existing runs; the child may still operate.


def finish_job(path, pid, *, certain):
    from ..actions.accessibility import save_object, _alive
    path = Path(path)
    value = _manifest(path)
    child = value.get("child")
    if not child or child.get("pid") != pid or _alive(child) is not False:
        return False
    value.update(state="complete" if certain else "unknown", finished_at=time.time())
    save_object(path, value)
    return True


def _consumers():
    """Read identities/session and run markers only; never retain environment."""
    deadline = time.monotonic() + 2
    sessions, runs, pids = set(), set(), set()
    for index, path in enumerate(Path("/proc").iterdir()):
        if index > 8192 or time.monotonic() > deadline:
            raise OSError("inventário de consumidores de temporários incompleto")
        if not path.name.isdigit():
            continue
        try:
            if path.stat().st_uid != os.getuid():
                continue
            fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
            if fields[0] == "Z":
                continue
            pids.add(int(path.name))
            sessions.add(int(fields[3]))
            with (path / "environ").open("rb") as stream:
                raw = stream.read(131073)
            if len(raw) > 131072:
                raise OSError("ambiente de consumidor excede orçamento")
            for part in raw.split(b"\0"):
                if part.startswith(b"FOLEGO_RUN_ID="):
                    runs.add(part.partition(b"=")[2].decode())
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (OSError, ValueError) as exc:
            raise OSError("propriedade de consumidores desconhecida; temporários preservados") from exc
    if os.getpid() not in pids:
        raise OSError("inventário de consumidores sem evidência do próprio processo")
    return sessions, runs, pids


def _archive_completed(root, *, mounts=None):
    """Same-filesystem rename, never payload deletion. Legacy/unknown stays put."""
    from ..actions.accessibility import _alive
    from ..actions.tmpfs.holders import holder_index
    from ..actions.disk.review import identity
    deadline = time.monotonic() + 3
    info = root.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise OSError("raiz de temporários sem propriedade/permissões privadas")
    candidates = []
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if index >= 258:
                break
            if not entry.name.startswith("run-") or not entry.is_dir(follow_symlinks=False):
                continue
            try:
                run = root / entry.name
                value = _manifest(run / "run.json")
                if (value.get("state") == "complete" and _alive(value.get("child")) is False
                        and type(value.get("session")) is int and value["session"] == value["child"]["pid"]):
                    candidates.append((run, value))
            except (OSError, ValueError):
                continue
    if not candidates:
        return {"archived": 0, "reason": "nenhum encerramento certificado"}
    try:
        sessions, consumers, pids = _consumers()
    except OSError as exc:
        return {"archived": 0, "reason": str(exc)}
    holders = holder_index(proc_root="/proc", pids=pids, prefixes=(str(root),),
                           include_process_refs=True, deadline_s=1, max_fds=16384)
    if holders.state != "complete":
        return {"archived": 0, "reason": "referências incompletas; temporários preservados"}
    archive = root / ".retained"
    archive.mkdir(mode=0o700, exist_ok=True)
    if archive.is_symlink() or archive.stat().st_uid != os.getuid() or archive.stat().st_mode & 0o077:
        raise OSError("arquivo de temporários não é privado")
    # Bounded retention without deleting evidence or raising the live-run cap.
    retained_bytes, retained_items = 0, 0
    for parent, directories, files in os.walk(archive, followlinks=False):
        for name in (*directories, *files):
            retained_items += 1
            if retained_items > 16384:
                return {"archived": 0, "reason": "retenção exige revisão; inventário excedeu orçamento"}
            retained_bytes += (Path(parent) / name).lstat().st_size
    count = 0
    for run, value in candidates[:16]:
        if time.monotonic() >= deadline: break
        if value["session"] in sessions or run.name in consumers or holders.pids_holding(str(run)):
            continue
        try:
            before = identity(run, max_entries=1024, timeout_s=.25)
        except (OSError, ValueError):
            continue
        size = 0
        protected = False
        for parent, directories, files in os.walk(run, followlinks=False):
            for name in (*directories, *files):
                path = Path(parent) / name
                info = path.lstat()
                retained_items += 1
                if (path.is_symlink() or info.st_dev != root.stat().st_dev or info.st_uid != os.getuid()
                        or retained_items > 16384):
                    protected = True
                    break
                size += info.st_size
            if protected:
                break
        if protected or size + retained_bytes > 1024**3:
            continue
        target = archive / run.name
        if target.exists():
            continue
        # Recheck identity immediately before moving the private completed tree.
        if _manifest(run / "run.json") != value or _alive(value["child"]) is not False:
            continue
        try:
            if identity(run, max_entries=1024, timeout_s=.25) != before: continue
        except (OSError, ValueError):
            continue
        os.rename(run, target)
        for directory in (root, archive):
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(fd)
            finally: os.close(fd)
        retained_bytes += size
        count += 1
    return {"archived": count, "retained_bytes": retained_bytes,
            "archive": str(archive), "reason": "conteúdo preservado em destino persistente; nada apagado"}


def retention_status(root):
    root = Path(root)
    try:
        root.lstat()
    except FileNotFoundError:
        return {"root": str(root), "runs": 0, "limit": 256, "state": "not-observed"}
    from ..actions.accessibility import private_path
    private_path(root / "run.json")
    rows = []
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if index >= 258:
                raise OSError("inventário de temporários excede orçamento")
            if entry.name in (".retention.lock", ".retained"):
                continue
            try:
                value = _manifest(root / entry.name / "run.json")
                state = value.get("state", "unknown")
            except (OSError, ValueError):
                state = "unknown"
            rows.append({"name": entry.name, "state": state})
    return {"root": str(root), "runs": len(rows), "limit": 256, "entries": rows,
            "archive": str(root / ".retained"), "state": "review" if len(rows) >= 240 else "observed"}


def retain_completed(root):
    root = Path(root)
    mounts, error = read_mounts_checked()
    if error or not destination_verdict(root, mounts=mounts).ok:
        raise OSError("destino persistente não comprovado")
    from ..actions.accessibility import private_path
    private_path(root / "run.json")
    with _root_lock(root):
        return _archive_completed(root, mounts=mounts)


def _register_root(root, env):
    from ..actions.accessibility import save_object, read_object
    home = Path(env.get("HOME", str(Path.home())))
    state = Path(env.get("XDG_STATE_HOME", str(home / ".local/state")))
    folder = state / "folego/job-roots"
    path = folder / (hashlib.sha256(str(root).encode()).hexdigest() + ".json")
    previous = read_object(path)
    expected = {"schema": 1, "root": str(root), "uid": os.getuid()}
    if previous is not None:
        if previous != expected:
            raise OSError("registro de raiz desconhecido; preservado")
        return  # An unchanged verified registration needs no repeated fsync.
    if folder.exists():
        with os.scandir(folder) as entries:
            for index, _ in enumerate(entries):
                if index >= 15:
                    raise OSError("raízes de temporários retidas exigem revisão")
    save_object(path, expected)


def maintain_registered(*, cursor=0):
    from .. import paths
    from ..actions.accessibility import read_object, private_path
    folder = paths.state_dir() / "job-roots"
    private_path(folder / "registry")
    try:
        names = []
        with os.scandir(folder) as entries:
            for entry in entries:
                names.append(folder / entry.name)
                if len(names) > 16:
                    raise OSError("registro de raízes excede orçamento")
    except FileNotFoundError:
        return {"archived": 0, "reason": "nenhuma raiz registrada"}
    if len(names) > 16:
        raise OSError("registro de raízes excede orçamento")
    if not names: return {"archived": 0, "reason": "registro vazio"}
    value = read_object(sorted(names)[cursor % len(names)])
    if not value or value.get("uid") != os.getuid() or not isinstance(value.get("root"), str):
        raise OSError("registro de raiz desconhecido; preservado")
    return retain_completed(value["root"])
