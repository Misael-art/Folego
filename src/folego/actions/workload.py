"""Admission for an explicitly participating foreground job. Never signals a process."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import uuid

from .. import paths
from ..core.collector import MetricsCollector
from ..core.policy import HealthThresholds
from ..core.sessions import SessionError
from ..core.tmpfs import read_mounts_checked
from ..safely.jobtemp import job_root_for, prepare_job_environment
from ..safely.mounts import destination_verdict
from .accessibility import private_path, read_object, save_object

HEAVY = {"cc1", "cc1plus", "rustc", "cargo", "ninja", "make", "cmake", "pytest", "makepkg",
         "pacman", "rpm", "dpkg", "qemu-system-x86", "ld.lld"}
MIB = 1024 ** 2


def _state():
    return paths.state_dir() / "foreground-work.json"


@contextmanager
def _reservation():
    path = _state().with_suffix(".lock")
    private_path(path, create=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("Trava de carga sem identidade privada")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SessionError("Outra solicitação está verificando a margem do host") from None
        yield
    finally:
        os.close(fd)


def _previous(snapshot, namespace):
    record = read_object(_state())
    if record is None:
        return None
    for key in ("boot_id", "session_id"):
        if not isinstance(record.get(key), str):
            raise ValueError("Identidade da reserva anterior ilegível")
        uuid.UUID(record[key])
    if any(type(record.get(key)) is not int or record[key] <= 0 for key in ("pid", "starttime", "namespace")):
        raise ValueError("Reserva anterior ilegível")
    report = {"session_id": record["session_id"], "pid": record["pid"], "state": "boot anterior"}
    if record["boot_id"] != snapshot.boot_id:
        return report
    if namespace != record["namespace"] or snapshot.source("processes").status != "ok":
        return dict(report, state="inventário incerto")
    members = [p for p in snapshot.procs if p.session == record["pid"] and p.state != "Z"]
    if not members:
        return dict(report, state="sessão liberada", processes=0)
    leader = next((p for p in members if p.pid == record["pid"]), None)
    state = "membros após saída do líder"
    if leader:
        state = "em execução" if leader.starttime == record["starttime"] else "SID reutilizado"
    return dict(report, state=state, processes=len(members), rss_kb=sum(p.rss_kb for p in members))


def _swap(root):
    fields = dict(line.split() for line in (root / "vmstat").read_text().splitlines())
    return int(fields["pswpin"]), int(fields["pswpout"])


def _free_mib(path, mounts):
    resolved = Path(path).resolve()
    verdict = destination_verdict(resolved, mounts=mounts)
    if not verdict.ok:
        raise ValueError(verdict.reason)
    while not resolved.exists():
        resolved = resolved.parent
    fs = os.statvfs(resolved)
    return fs.f_bavail * fs.f_frsize // MIB


def capacity(ram_mib, disk_mib, dest):
    """Measures on demand; a recommendation expires when a participant starts."""
    if type(ram_mib) is not int or ram_mib <= 0 or type(disk_mib) is not int or disk_mib < 0:
        raise ValueError("Informe pico de RAM positivo e saída total em disco não negativa (MiB)")
    root = Path(paths.proc_root())
    if (root / "1/comm").read_text().strip() not in ("systemd", "init"):
        raise ValueError("O coletor precisa observar os processos da sessão no host")
    mounts, problem = read_mounts_checked()
    if problem:
        raise ValueError(problem)
    if not Path(dest).is_dir():
        raise ValueError("Destino da carga deve ser um diretório existente")
    namespace = (root / "self/ns/pid").stat().st_ino
    try:
        deck = (Path(paths.sys_root()) / "class/dmi/id/product_name").read_text().strip() == "Jupiter"
    except OSError:
        deck = False
    before = _swap(root)
    time.sleep(1)
    snapshot = MetricsCollector().collect()
    uuid.UUID(snapshot.boot_id)
    after = _swap(root)
    unknown, wait = [], []
    previous = _previous(snapshot, namespace)
    if previous and previous["state"] in ("inventário incerto", "SID reutilizado"):
        unknown.append("Reserva anterior sem identidade verificável")
    elif previous and previous["state"] in ("em execução", "membros após saída do líder"):
        wait.append(previous["state"])
    if snapshot.source("processes").status != "ok":
        unknown.append("Inventário de processos incompleto")
    busy = sorted({p.comm for p in snapshot.procs if p.state != "Z" and
                   (p.comm in HEAVY or "pytest" in p.cmdline[:3] or
                    any(arg.endswith(("/pytest", "/pytest.py")) for arg in p.cmdline[:3]))})
    if busy:
        wait.append("Outra carga local: " + ", ".join(busy))
    mem = snapshot.mem
    reserve = None
    if mem is None or snapshot.source("meminfo").status != "ok":
        unknown.append("RAM indisponível")
    else:
        reserve = max(4096 if deck else 512, (mem.mem_total_kb + 4095) // 4096)
        if mem.mem_available_kb < (ram_mib + reserve) * 1024:
            wait.append("RAM insuficiente após o pico estimado")
    if any(b < a for a, b in zip(before, after)):
        unknown.append("Contadores de swap descontínuos")
    elif after != before:
        wait.append("Paginação ativa durante a leitura")
    for name, monitor, threshold in (("CPU", snapshot.pressure_cpu, 20),
                                     ("I/O", snapshot.pressure_io, 5),
                                     ("RAM", snapshot.pressure_memory, HealthThresholds().psi_memory_yellow)):
        if monitor is None:
            unknown.append(f"Pressão de {name} indisponível")
        elif max(monitor.some_avg10, monitor.some_avg60) >= threshold:
            wait.append(f"Espera elevada por {name}")
    if snapshot.temperature_c is None or snapshot.thermal_passive_c is None:
        unknown.append("Temperatura ou limite passivo do sensor indisponível")
    else:
        limit = snapshot.thermal_passive_c - 10
        if snapshot.temperature_c >= (min(90, limit) if deck else limit):
            wait.append("Margem térmica insuficiente")
    tmp_root = job_root_for(os.environ, mounts)
    free = min(_free_mib(dest, mounts), _free_mib(tmp_root, mounts))
    if free < disk_mib + 10240:
        wait.append("Espaço insuficiente para saída, temporários e reserva")
    return {"decision": "unknown" if unknown else "wait" if wait else "ready", "reasons": unknown + wait,
            "previous": previous, "boot_id": snapshot.boot_id, "namespace": namespace,
            "observed_mono": snapshot.mono, "ram_reserve_mib": reserve, "disk_available_mib": free, "retry_after_s": 20 if unknown or wait else None}


def launch(args, argv, store):
    with _reservation():
        result = capacity(args.ram_mib, args.disk_mib, args.destination)
        if result["decision"] != "ready":
            raise SessionError(" · ".join(result["reasons"]) + " · reavaliar em 20 s")
        env = prepare_job_environment()
        # EOF cancels an uncommitted start. Once released, the command survives its launcher.
        reader, writer = os.pipe()
        child = None
        try:
            child = subprocess.Popen([sys.executable, "-I", "-m", "folego.process.job_child",
                                      "--admission-fd", str(reader), env["FOLEGO_RUN_MANIFEST"], "--", *argv], pass_fds=(reader,), start_new_session=True, env=env)
            session = store.register_child(child, project=args.project, label=args.label, keep_active=True)
            save_object(_state(), {"schema": 1, "boot_id": session.boot_id, "pid": child.pid,
                                   "starttime": session.starttime, "session_id": session.session_id,
                                   "namespace": result["namespace"]})
            if time.monotonic() - result["observed_mono"] > HealthThresholds().stale_after_s:
                raise SessionError("A reserva demorou além da validade da amostra; comando preservado na origem")
            os.write(writer, b"1")
        except BaseException:
            os.close(writer)
            writer = None
            if child is not None:
                child.wait(timeout=3)
            raise
        finally:
            os.close(reader)
            if writer is not None:
                os.close(writer)
        return child, session, env["FOLEGO_RUN_MANIFEST"]
