"""Read-only Linux probes and a private, bounded history for Modo Auditor."""
from contextlib import closing, contextmanager
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import stat
import subprocess
import time
from urllib.parse import quote

from .. import audit_profile, paths
from ..actions.accessibility import private_path
from ..core.collector import MetricsCollector
from ..core.instance import InstanceLock
from ..core.sessions import read_boot_id
from ..safely.atomicfile import fsync_dir
from ..safely.mounts import destination_verdict
from .accessibility import bounded_command
from .host_storage import read_mountinfo
from .host_timeline import HostTimelineRecorder, _BOOT_ID, _sample

MAX_BYTES = 64 * 1024 * 1024
INTERVAL = 60
PACKAGE_INTERVAL = 300
JOURNAL_LIMIT = 256
CRASH_ID = "fc2e22bc6ee647b6b90729ab34a250b1"
LABELS = {
    "metrics": "Recursos", "boot": "Tempo de boot", "system": "Sistema",
    "packages": "Pacotes do sistema",
    "flatpak-system": "Flatpak do sistema", "flatpak-user": "Flatpak do usuário",
    "services-system": "Serviços do sistema", "services-user": "Serviços do usuário",
    "enabled-system": "Habilitação no sistema", "enabled-user": "Habilitação no usuário",
    "disks": "Discos e partições", "mounts": "Montagens",
    "journal": "Avisos e erros", "crash": "Falhas de aplicativos",
}
BOOT_TIMINGS = {
    "total_s": "Do firmware ao fim da inicialização",
    "system_s": "Do kernel ao fim da inicialização",
    "firmware_s": "Firmware", "loader_s": "Carregador de boot",
    "kernel_s": "Kernel", "initrd_s": "Initrd", "userspace_s": "Serviços do sistema",
    "graphical_target_s": "Do kernel ao alvo gráfico",
}
KERNEL_INCIDENTS = {
    "memória esgotada": re.compile(r"out of memory|oom.kill|invoked oom", re.I),
    "temperatura": re.compile(r"thermal|overheat|temperature above", re.I),
    "armazenamento": re.compile(r"btrfs|ntfs|nvme|I/O error|blk_update_request", re.I),
    "GPU": re.compile(r"amdgpu|gpu hang|gpu reset|ring .*timeout", re.I),
    "processo abortado": re.compile(r"segfault|general protection fault", re.I),
    "travamento": re.compile(r"watchdog|soft lockup|hard lockup|hung task", re.I),
}


def _database():
    return paths.state_dir() / "host-audit.sqlite3"


def _iso(ts):
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="milliseconds")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@contextmanager
def _connect(*, write):
    path = _database()
    private_path(path, create=write)
    if write:
        mounts = read_mountinfo(Path(paths.proc_root()))
        verdict = destination_verdict(path.parent, mounts=((row["mount"], row["type"]) for row in mounts))
        if not verdict.ok:
            raise ValueError(verdict.reason)
        space = os.statvfs(path.parent)
        if space.f_bavail * space.f_frsize < 2 * MAX_BYTES:
            raise ValueError("Espaço insuficiente para o histórico e seu diário de gravação")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
            fsync_dir(path.parent)
    for candidate in (path, path.with_suffix(path.suffix + "-journal")):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            if candidate == path:
                raise
            continue
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > MAX_BYTES):
            raise ValueError("arquivo de auditoria fora do orçamento ou sem proteção local")
    mode = "rw" if write else "ro"
    with closing(sqlite3.connect(f"file:{quote(str(path))}?mode={mode}", uri=True, timeout=1)) as db:
        schema = db.execute("PRAGMA user_version").fetchone()[0]
        if schema == 0 and write:
            if path.stat().st_size:
                raise ValueError("histórico de auditoria sem schema reconhecido")
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, boot TEXT NOT NULL,
                    source TEXT NOT NULL, kind TEXT NOT NULL, subject TEXT NOT NULL,
                    data TEXT NOT NULL, journal_id TEXT UNIQUE
                );
                CREATE INDEX events_at ON events(at, id);
                CREATE INDEX events_boot ON events(boot, at, id);
                CREATE TABLE sources (
                    name TEXT PRIMARY KEY, checked REAL NOT NULL, quality TEXT NOT NULL,
                    reason TEXT NOT NULL, confirmed REAL, boot TEXT, inventory TEXT
                );
                PRAGMA user_version = 1;
                COMMIT;
            """)
        elif schema != 1:
            raise ValueError("schema de auditoria desconhecido; histórico preservado")
        if write:
            db.execute("PRAGMA synchronous=FULL")
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            db.execute(f"PRAGMA max_page_count={MAX_BYTES // page_size}")
        with db:
            yield db


def _query(*argv, budget=262144):
    if not shutil.which(argv[0]):
        raise FileNotFoundError(f"{argv[0]} indisponível")
    result = bounded_command(list(argv), timeout=3, max_bytes=budget,
                             env={**os.environ, "LC_ALL": "C", "SYSTEMD_COLORS": "0"})
    if result.returncode:
        raise ValueError(f"{argv[0]} não confirmou a consulta (código {result.returncode})")
    if "\ufffd" in result.stdout:
        raise ValueError(f"saída de {argv[0]} contém texto ilegível")
    return result


def _rows(raw, width, *, allow_empty=False):
    rows = {}
    for line in raw.splitlines():
        columns = line.split(maxsplit=width)[:width]
        if (len(columns) != width or columns[0] in rows or len(line) > 1024
                or len(rows) >= 20000 or any(len(col) > 256 for col in columns)):
            raise ValueError("inventário incompleto ou fora do orçamento")
        rows[columns[0]] = " ".join(columns[1:])
    if not rows and not allow_empty:
        raise ValueError("fonte retornou inventário vazio")
    return rows


def _packages():
    pacman = Path("/var/lib/pacman/local")
    if pacman.is_dir():
        before = pacman.stat().st_mtime_ns
        lock = pacman.parent / "db.lck"
        if lock.exists():
            raise ValueError("transação de pacotes pacman em andamento")
        command = ("pacman", "-Q")
        result = _rows(_query(*command, budget=2**21).stdout, 2)
        if lock.exists() or pacman.stat().st_mtime_ns != before:
            raise ValueError("base pacman mudou durante a leitura")
        return result
    if Path("/var/lib/dpkg/status").is_file():
        command = ("dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${db:Status-Status}\n")
        raw = _query(*command, budget=2**21).stdout
        rows = []
        for line in raw.splitlines():
            name, version, state = line.split("\t")
            if state == "installed":
                rows.append(f"{name} {version}")
        return _rows("\n".join(rows), 2)
    command = ("rpm", "-qa", "--qf", "%{NAME}.%{ARCH} %{EPOCHNUM}:%{VERSION}-%{RELEASE}\n")
    raw = _query(*command, budget=2**21).stdout
    # Multiple kernel versions can coexist under one name/architecture in RPM.
    versions = {}
    for entry in raw.splitlines():
        name, version = entry.split()
        versions.setdefault(name, set()).add(version)
    return _rows("\n".join(f"{name} {','.join(sorted(items))}" for name, items in versions.items()), 2)


def _flatpak(scope):
    raw = _query("flatpak", f"--{scope}", "list", "--columns=ref,version,active").stdout
    rows = {}
    for line in raw.splitlines():
        ref, version, commit = line.split("\t")
        if (not re.fullmatch(r"(?:app/|runtime/)?[\w.-]+/[\w.-]+/[\w.-]+", ref)
                or ref in rows or len(line) > 512):
            raise ValueError("inventário Flatpak inválido")
        rows[ref] = {"version": version, "commit": commit}
    return rows


def _services(scope, *, installed):
    args = ["systemctl", f"--{scope}", "--no-pager", "--no-legend", "--plain", "--type=service"]
    if installed:
        return _rows(_query(*args, "list-unit-files").stdout, 2)
    args += ["--state=active,failed,activating,deactivating,reloading"]
    return _rows(_query(*args, "list-units").stdout, 4, allow_empty=True)


def _system():
    platform.invalidate_caches()
    release = platform.freedesktop_os_release()
    uname = os.uname()
    return {"kernel": uname.release, "machine": uname.machine,
            **{key: release[key] for key in ("ID", "PRETTY_NAME", "VERSION_ID", "BUILD_ID")
               if key in release}}


def _boot_times(boot):
    properties = (
        "FirmwareTimestampMonotonic", "LoaderTimestampMonotonic", "InitRDTimestampMonotonic",
        "UserspaceTimestampMonotonic", "FinishTimestampMonotonic", "SecurityStartTimestampMonotonic",
        "FinishTimestamp", "SoftRebootsCount",
    )
    if read_boot_id() != boot:
        raise ValueError("Identidade do boot atual não comprovada")
    raw = _query("systemctl", "--system", "--no-pager", "--all", "--timestamp=unix",
                 "--property=" + ",".join(properties), "show", budget=4096).stdout
    values = dict(line.split("=", 1) for line in raw.splitlines())
    if int(values.get("SoftRebootsCount", 0)):
        raise ValueError("Reinício em software sem medida de um novo boot completo")
    firmware, loader, initrd, userspace, finish, security = (int(values[key]) for key in properties[:6])
    if finish == 0:
        raise ValueError("O systemd ainda está inicializando")
    if security == 0:
        raise ValueError("O systemd não confirmou uma inicialização do host")
    if (min(firmware, loader, initrd) < 0 or (firmware and firmware < loader)
            or not 0 < userspace < finish <= time.monotonic() * 1e6 or initrd > userspace
            or not 0 < security <= finish):
        raise ValueError("Marcos do systemd incoerentes")
    try:
        graphical = int(_query("systemctl", "--system", "--no-pager", "--value",
                               "--property=ActiveEnterTimestampMonotonic", "show", "graphical.target",
                               budget=4096).stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        graphical = None
    if read_boot_id() != boot:
        raise ValueError("O boot mudou durante a leitura")
    stamp = values.get("FinishTimestamp", "")
    ended_at = int(stamp[1:]) if re.fullmatch(r"@[0-9]{1,12}", stamp) else None
    timings = {
        "total_s": (firmware + finish) / 1e6 if firmware else None,
        "system_s": finish / 1e6,
        "firmware_s": (firmware - loader) / 1e6 if firmware and loader else None,
        "loader_s": loader / 1e6 if loader else None,
        "kernel_s": (initrd or userspace) / 1e6,
        "initrd_s": (userspace - initrd) / 1e6 if initrd else None,
        "userspace_s": (finish - userspace) / 1e6,
        "graphical_target_s": graphical / 1e6 if graphical and userspace <= graphical <= finish else None,
    }
    return ended_at, timings


def boot_seconds(seconds):
    milliseconds = round(seconds * 1000)
    minutes, remainder = divmod(milliseconds, 60000)
    value = f"{remainder / 1000:.3f}".replace(".", ",")
    return f"{minutes} min {value} s" if minutes else f"{value} s"


def _mounts():
    rows = {}
    for mount in read_mountinfo(Path(paths.proc_root())):
        location, source = mount["mount"], mount["source"]
        if location == "/" or location == "/home" or source.startswith("/dev/") or mount["type"] in (
                "nfs", "nfs4", "cifs", "smb3", "fuse.sshfs"):
            rows.setdefault(location, []).append({key: mount[key] for key in ("source", "type")})
    return rows


def _disks():
    raw = _query("lsblk", "--json", "--bytes", "--list",
                 "--output=NAME,TYPE,SIZE,FSTYPE,UUID,PARTUUID,RO").stdout
    items = json.loads(raw)["blockdevices"]
    rows = {}
    for item in items:
        name = item["name"]
        if not isinstance(name, str) or name in rows or not isinstance(item["type"], str):
            raise ValueError("inventário de blocos inválido")
        if item["type"] not in ("loop", "rom") or item["fstype"]:
            rows[name] = {key: val for key, val in item.items() if key != "name"}
    return rows


def _disk_capacity():
    volumes = {}
    for label, path in (("system", "/"), ("home", Path.home())):
        try:
            vfs = os.statvfs(path)
            volumes[label] = {"total_bytes": vfs.f_blocks * vfs.f_frsize,
                              "available_bytes": vfs.f_bavail * vfs.f_frsize}
        except OSError:
            volumes[label] = None
    return volumes


def _journal(boot, at, since, *, crash):
    fields = "MESSAGE,_COMM,_TRANSPORT,PRIORITY,MESSAGE_ID,UNIT,USER_UNIT,_SYSTEMD_UNIT,_SYSTEMD_USER_UNIT"
    args = ["journalctl", "--no-pager", "--boot=" + boot.replace("-", ""),
            f"--since=@{since:.6f}", f"--until=@{at:.6f}", "-n", str(JOURNAL_LIMIT + 1),
            "-o", "json", "--output-fields=" + fields + ",COREDUMP_COMM,COREDUMP_UNIT,COREDUMP_USER_UNIT"]
    args += ["MESSAGE_ID=" + CRASH_ID] if crash else ["--priority=warning"]
    result = _query(*args)
    lines = result.stdout.splitlines()
    limited = len(lines) > JOURNAL_LIMIT or bool(result.stderr.strip())
    events = []
    for line in lines[-JOURNAL_LIMIT:]:
        row = json.loads(line)
        if not crash and row.get("MESSAGE_ID") == CRASH_ID:
            continue
        stamp = int(row["__REALTIME_TIMESTAMP"]) / 1e6
        if row["_BOOT_ID"] != boot.replace("-", "") or not since <= stamp <= at:
            raise ValueError("evidência do journal fora da janela")
        identifier = sha256(row["__CURSOR"].encode()).hexdigest()
        unit_fields = ("COREDUMP_USER_UNIT", "COREDUMP_UNIT", "USER_UNIT", "UNIT",
                       "_SYSTEMD_USER_UNIT", "_SYSTEMD_UNIT")
        metadata = {key: val for key, val in row.items() if key in
                    (*unit_fields, "_COMM", "_TRANSPORT", "PRIORITY", "MESSAGE_ID", "COREDUMP_COMM",
                     "__MONOTONIC_TIMESTAMP") and isinstance(val, str) and len(val) <= 256}
        subject = (metadata.get("COREDUMP_COMM") if crash else None) or next(
            (metadata[key] for key in unit_fields if key in metadata), metadata.get("_COMM", "journal"))
        if metadata.get("_TRANSPORT") == "kernel" and isinstance(message := row.get("MESSAGE"), str):
            category = next((key for key, pattern in KERNEL_INCIDENTS.items() if pattern.search(message)), "")
            if category:
                metadata["category"] = category
                subject = f"{subject} · {category}"
        events.append((stamp, subject, metadata, identifier))
    return events, "Acesso ou janela do journal parcial" if limited else ""


def _event(db, at, boot, source, kind, subject, data, journal_id=None):
    db.execute("INSERT INTO events(at,boot,source,kind,subject,data,journal_id) VALUES(?,?,?,?,?,?,?) "
               "ON CONFLICT(journal_id) DO NOTHING",
               (at, boot, source, kind, subject, _json(data), journal_id))


def _record_boot(db, boot):
    previous = db.execute("SELECT boot, quality, reason FROM sources WHERE name='boot'").fetchone()
    if previous and previous[0] == boot and previous[1] in ("ok", "partial"):
        return
    if db.execute("SELECT 1 FROM events WHERE boot=? AND source='boot' AND kind='startup'", (boot,)).fetchone():
        return
    checked = time.time()
    confirmed = None
    try:
        ended_at, times = _boot_times(boot)
    except (OSError, ValueError, subprocess.SubprocessError, KeyError) as exc:
        quality = "unsupported" if isinstance(exc, FileNotFoundError) else "unknown"
        reason = str(exc)[:240]
        if previous != (boot, quality, reason):
            _event(db, checked, boot, "boot", "source", "", {"quality": quality, "reason": reason})
    else:
        confirmed = time.time()
        ended_at = ended_at if ended_at and ended_at <= confirmed else None
        missing = []
        if times["firmware_s"] is None:
            missing.append("firmware ou carregador com leitura incompleta")
        if ended_at is None:
            missing.append("horário de conclusão indisponível")
        quality = "partial" if missing else "ok"
        reason = " · ".join(missing)
        label = "Total " + boot_seconds(times["total_s"]) if times["total_s"] is not None else (
            "Sistema " + boot_seconds(times["system_s"]))
        _event(db, ended_at or confirmed, boot, "boot", "startup", label,
               {**times, "quality": quality, "reason": reason, "observed_at": _iso(confirmed)})
    db.execute("INSERT OR REPLACE INTO sources VALUES('boot',?,?,?,?,?,NULL)",
               (checked, quality, reason, confirmed, boot))


def _record_source(db, boot, at, name, probe, *, journal=False):
    previous = db.execute(
        "SELECT quality, reason, confirmed, boot, inventory FROM sources WHERE name=?", (name,)).fetchone()
    old_quality, old_reason, confirmed, old_boot, stored = previous or (None, "", None, None, None)
    quality, reason, inventory = "ok", "", stored
    try:
        if old_boot == boot and confirmed is not None and confirmed > at:
            raise ValueError("relógio de parede regrediu desde a última leitura comprovada")
        value = probe(confirmed if old_boot == boot and confirmed is not None else at - 300)
    except (OSError, ValueError, subprocess.SubprocessError, KeyError, TypeError) as exc:
        quality = "unsupported" if isinstance(exc, FileNotFoundError) else "unknown"
        reason = str(exc)[:240]
    else:
        if journal:
            events, reason = value
            for stamp, subject, data, identifier in events:
                _event(db, stamp, boot, name, "incident", subject, data, identifier)
            if reason:
                quality = "partial"
        else:
            old = json.loads(stored) if stored is not None else None
            if old is None:
                _event(db, at, boot, name, "baseline", "", {"items": len(value)})
            else:
                for item in sorted(old.keys() | value.keys()):
                    before, after = old.get(item), value.get(item)
                    if before == after:
                        continue
                    kind = "added" if item not in old else "removed" if item not in value else "changed"
                    _event(db, at, boot, name, kind, item, {
                        "before": before, "after": after, "last_observed_at": _iso(confirmed),
                        "last_observed_boot": old_boot,
                    })
            inventory = _json(value)
        confirmed, old_boot = at, boot
    if (quality, reason) != (old_quality, old_reason) and (quality != "ok" or old_quality not in (None, "ok")):
        _event(db, at, boot, name, "source", "", {"quality": quality, "reason": reason})
    db.execute("INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?,?)",
               (name, at, quality, reason, confirmed, old_boot, inventory))


class HostAuditRecorder:
    def __init__(self):
        self._last = -float("inf")
        self._last_package = -float("inf")
        self._boot = None
        self.error = ""

    def record(self, snapshot):
        if audit_profile.status()["enabled"] is not True:
            self._last = self._last_package = -float("inf")
            self._boot = None
            return
        boot, at, mono = snapshot.boot_id, snapshot.ts, snapshot.mono
        if not _BOOT_ID.fullmatch(boot or ""):
            self.error = "boot ID ausente ou inválido"
            return
        if boot != self._boot:
            self._boot = boot
            self._last = self._last_package = -float("inf")
        if mono - self._last < INTERVAL:
            return
        self._last = mono
        probes = {
            "system": _system,
            "services-system": lambda: _services("system", installed=False),
            "services-user": lambda: _services("user", installed=False),
            "enabled-system": lambda: _services("system", installed=True),
            "enabled-user": lambda: _services("user", installed=True),
            "disks": _disks, "mounts": _mounts,
        }
        if mono - self._last_package >= PACKAGE_INTERVAL:
            probes.update({"packages": _packages, "flatpak-system": lambda: _flatpak("system"),
                           "flatpak-user": lambda: _flatpak("user")})
            self._last_package = mono
        metrics = _sample(snapshot)
        metrics.update(cpu_busy_frac=snapshot.cpu_busy_frac,
                       thermal_passive_c=snapshot.thermal_passive_c,
                       thermal_critical_c=snapshot.thermal_critical_c,
                       disk_capacity=_disk_capacity())
        try:
            # Record metrics before probing slower sources. Each source commits
            # independently, so an interruption retains the completed evidence.
            with _connect(write=True) as db:
                _event(db, at, boot, "metrics", "sample", "", metrics)
                db.commit()
                _record_boot(db, boot)
                db.commit()
                for name, probe in probes.items():
                    started = time.time()
                    _record_source(db, boot, started, name, lambda _: probe())
                    db.commit()
                for name in ("crash", "journal"):
                    now = time.time()
                    _record_source(db, boot, now, name, lambda since: _journal(
                        boot, now, since, crash=name == "crash"), journal=True)
                    db.commit()
            self.error = ""
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.error = f"histórico de auditoria indisponível: {exc}"


def history(*, source=None, boot=None, since=None, until=None, before_id=None, changes_only=False, limit=100):
    if boot is not None and not _BOOT_ID.fullmatch(boot):
        raise ValueError("boot ID inválido")
    if not 1 <= limit <= 2000:
        raise ValueError("limite deve estar entre 1 e 2000")
    filters, values = [], []
    if changes_only:
        filters.append("kind != 'sample'")
    if before_id is not None:
        filters.append("(at, id) < (SELECT at, id FROM events WHERE id = ?)")
        values.append(before_id)
    for sql, value in (("source = ?", source), ("boot = ?", boot), ("at >= ?", since), ("at < ?", until)):
        if value is not None:
            filters.append(sql)
            values.append(value)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    try:
        with _connect(write=False) as db:
            if before_id is not None and not db.execute("SELECT 1 FROM events WHERE id = ?", (before_id,)).fetchone():
                raise ValueError("ID de paginação não encontrado")
            records = db.execute("SELECT id, at, boot, source, kind, subject, data FROM events"
                                 + where + " ORDER BY at DESC, id DESC LIMIT ?", (*values, limit + 1)).fetchall()
            sources = db.execute("SELECT name, checked, quality, reason, confirmed FROM sources ORDER BY name").fetchall()
        size = _database().stat().st_size
    except FileNotFoundError:
        return {"quality": "missing", "events": [], "sources": {}, "reason": "Nenhuma coleta de auditoria registrada."}
    except (ValueError, OSError, sqlite3.Error) as exc:
        return {"quality": "unknown", "events": [], "sources": {}, "reason": str(exc)}
    return {"quality": "ok" if all(row[2] == "ok" for row in sources) else "partial",
            "limited": len(records) > limit, "size_bytes": size, "limit_bytes": MAX_BYTES,
            "reason": "Histórico próximo do limite" if size >= MAX_BYTES * .9 else "",
            "sources": {name: {"checked": _iso(checked), "quality": quality, "reason": reason,
                               "confirmed": _iso(confirmed) if confirmed is not None else None}
                        for name, checked, quality, reason, confirmed in sources},
            "events": [{"id": key, "at": _iso(at), "boot_id": boot_id, "source": name,
                        "kind": kind, "subject": subject, "data": json.loads(data)}
                       for key, at, boot_id, name, kind, subject, data in reversed(records[:limit])]}


def watch():
    """Foreground collector for a session without the GUI."""
    with InstanceLock():
        collector = MetricsCollector()
        timeline, audit = HostTimelineRecorder(), HostAuditRecorder()
        collector.collect()  # Prime the CPU deltas used in the first persisted sample.
        while audit_profile.status()["enabled"] is True:
            started = time.monotonic()
            snapshot = collector.collect()
            timeline.record(snapshot)
            audit.record(snapshot)
            yield {"ok": not audit.error, "at": _iso(snapshot.ts),
                   "reason": audit.error, "timeline_issue": timeline.last_error}
            time.sleep(max(1, 15 - (time.monotonic() - started)))
