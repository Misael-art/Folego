"""Opt-in local session/artifact registry. Pure Python, no Qt, no mutation of /proc.

Why this exists: an agent that loses its connection may leave a useful build
running. Age, PPID=1 and low CPU cannot distinguish that from a leftover. A
session is an explicit statement from a launcher: "this UUID owns these PIDs and
artifacts; keep them alive until I end them or the heartbeat expires".

The registry is opt-in by construction: no file is created until a caller runs
`register()`. A missing file is an empty registry, never an inferred one. The
JSON is versioned and private; a corrupt file raises `SessionError`, and callers
must fail closed instead of assuming "no sessions".

States are distinct: `active` (heartbeat fresh), `disconnected` (the client said
it left but the process may still run), `heartbeat_lost` (no beat within the
policy), `ended` (explicit end, reboot, or PID death/reuse). Persisted data uses
wall time and boot_id; monotonic time is not meaningful across reboots.
"""
import contextlib
import fcntl
import json
import math
import os
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from .. import paths
from ..safely.atomicfile import write_atomic
from . import procfs

SCHEMA_VERSION = 1
ACTIVE = "active"
DISCONNECTED = "disconnected"
HEARTBEAT_LOST = "heartbeat_lost"
ENDED = "ended"
STATES = (ACTIVE, DISCONNECTED, HEARTBEAT_LOST, ENDED)


class SessionError(Exception):
    """The registry cannot be read, validated, or updated safely."""


@dataclass(frozen=True)
class SessionPolicy:
    heartbeat_ttl_s: float = 900.0
    artifact_ttl_days: float = 7.0


@dataclass(frozen=True)
class Artifact:
    path: str
    kind: str = "file"
    size_bytes: int | None = None
    created_at: float = 0.0
    expires_at: float | None = None

    def to_dict(self) -> dict:
        return {"path": self.path, "kind": self.kind,
                "size_bytes": self.size_bytes, "created_at": self.created_at,
                "expires_at": self.expires_at}

    @classmethod
    def from_dict(cls, data: dict) -> "Artifact":
        path = data.get("path")
        if (not isinstance(path, str) or not path or "\x00" in path
                or not os.path.isabs(path)):
            raise SessionError("artefato exige caminho absoluto e sem NUL")
        size = data.get("size_bytes")
        if size is not None and (not isinstance(size, int) or size < 0):
            raise SessionError(f"tamanho inválido para artefato {path!r}")
        expires = data.get("expires_at")
        if expires is not None and not isinstance(expires, (int, float)):
            raise SessionError(f"expiração inválida para artefato {path!r}")
        return cls(path=path, kind=str(data.get("kind", "file")),
                   size_bytes=size, created_at=float(data.get("created_at", 0.0)),
                   expires_at=None if expires is None else float(expires))


@dataclass(frozen=True)
class Session:
    session_id: str
    pid: int
    starttime: int
    boot_id: str
    uid: int
    created_at: float
    heartbeat_at: float
    state: str = ACTIVE
    project: str = ""
    label: str = ""
    keep_active: bool = False
    cgroup: str | None = None
    cgroup_verified: bool = False
    disconnected_at: float | None = None
    ended_at: float | None = None
    ended_reason: str | None = None
    artifacts: tuple[Artifact, ...] = ()

    @property
    def ended(self) -> bool:
        return self.state == ENDED

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id, "pid": self.pid,
            "starttime": self.starttime, "boot_id": self.boot_id, "uid": self.uid,
            "created_at": self.created_at, "heartbeat_at": self.heartbeat_at,
            "state": self.state, "project": self.project, "label": self.label,
            "keep_active": self.keep_active, "cgroup": self.cgroup,
            "cgroup_verified": self.cgroup_verified,
            "disconnected_at": self.disconnected_at, "ended_at": self.ended_at,
            "ended_reason": self.ended_reason,
            "artifacts": [item.to_dict() for item in self.artifacts],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        try:
            session_id = str(uuid.UUID(str(data["session_id"])))
            pid = int(data["pid"])
            starttime = int(data["starttime"])
            uid = int(data["uid"])
            created_at = float(data["created_at"])
            heartbeat_at = float(data["heartbeat_at"])
            state = str(data["state"])
            boot_id = str(data["boot_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionError(f"sessão inválida: {exc}") from exc
        if pid <= 0 or starttime < 0 or uid < 0:
            raise SessionError("sessão com pid/starttime/uid inválido")
        if state not in STATES:
            raise SessionError(f"estado de sessão desconhecido: {state!r}")
        artifacts = data.get("artifacts", [])
        if not isinstance(artifacts, list):
            raise SessionError("artefatos não são uma lista")
        return cls(
            session_id=session_id, pid=pid, starttime=starttime, boot_id=boot_id,
            uid=uid, created_at=created_at, heartbeat_at=heartbeat_at,
            state=state, project=str(data.get("project", "")),
            label=str(data.get("label", "")),
            keep_active=bool(data.get("keep_active", False)),
            cgroup=data.get("cgroup"),
            cgroup_verified=bool(data.get("cgroup_verified", False)),
            disconnected_at=data.get("disconnected_at"),
            ended_at=data.get("ended_at"),
            ended_reason=data.get("ended_reason"),
            artifacts=tuple(Artifact.from_dict(item) for item in artifacts),
        )


def read_boot_id(proc_root: str | Path | None = None) -> str:
    root = Path(proc_root) if proc_root else Path(paths.proc_root())
    try:
        return (root / "sys" / "kernel" / "random" / "boot_id").read_text().strip()
    except OSError:
        return ""


def read_cgroup(pid: int, proc_root: str | Path | None = None) -> str | None:
    """Caminho de cgroup v2 (ou name=systemd v1), somente se legível e de usuário.

    Experimental by design: a readable cgroup is evidence of capability, not a
    promise that a user unit exists. No unit is created or signalled here.
    """
    root = Path(proc_root) if proc_root else Path(paths.proc_root())
    try:
        raw = (root / str(pid) / "cgroup").read_text()
    except OSError:
        return None
    v2 = v1 = None
    for line in raw.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        hierarchy, controllers, path = parts
        if hierarchy == "0" and controllers == "" and path.startswith("/"):
            v2 = path
        elif "name=systemd" in controllers.split(","):
            v1 = path
    path = v2 or v1
    if not path or path == "/":
        return None
    # A sessão só é verificável dentro da fatia do usuário; um cgroup de serviço
    # de sistema pertence a outro domínio e não deve ser agrupado como sessão.
    if not (path.startswith("/user.slice/") or path.startswith("/user@")
            or path.startswith("/user.slice")):
        return None
    return path


class SessionRegistry:
    def __init__(self, path: Path | str | None = None, *, proc_root=None,
                 clock=time.time, boot_id_fn=read_boot_id,
                 policy: SessionPolicy | None = None):
        self.path = Path(path) if path else paths.sessions_path()
        self.proc_root = Path(proc_root) if proc_root else Path(paths.proc_root())
        self._clock = clock
        self._boot_id_fn = boot_id_fn
        self.policy = policy or SessionPolicy()
        self._lock_path = self.path.with_name(self.path.name + ".lock")

    # ------------------------------------------------------------- persistence

    @contextlib.contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _load(self) -> list[Session]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError) as exc:
            raise SessionError(f"registro de sessões ilegível: {exc}") from exc
        if not isinstance(raw, dict):
            raise SessionError("registro de sessões não é um objeto")
        if raw.get("version") != SCHEMA_VERSION:
            raise SessionError(f"versão de sessões não suportada: {raw.get('version')!r}")
        sessions = raw.get("sessions")
        if not isinstance(sessions, list):
            raise SessionError("campo sessions inválido")
        return [Session.from_dict(item) for item in sessions]

    def _save(self, sessions: list[Session]) -> None:
        payload = json.dumps({"version": SCHEMA_VERSION,
                              "sessions": [item.to_dict() for item in sessions]},
                             ensure_ascii=False, sort_keys=True).encode("utf-8")
        try:
            write_atomic(self.path, payload, mode=0o600)
        except OSError as exc:
            raise SessionError(f"não foi possível gravar o registro: {exc}") from exc

    # ---------------------------------------------------------------- liveness

    def _boot(self) -> str:
        boot = self._boot_id_fn(str(self.proc_root))
        if not boot:
            raise SessionError("boot_id indisponível: não é possível distinguir reboots")
        return boot

    def _refresh(self, session: Session, now: float, boot: str) -> Session:
        if session.state == ENDED:
            return session
        if boot and session.boot_id != boot:
            return replace(session, state=ENDED, ended_at=now,
                           ended_reason="boot mudou desde o registro")
        live = procfs.read_proc(self.proc_root, session.pid)
        if live is None or live.state == "Z":
            return replace(session, state=ENDED, ended_at=now,
                           ended_reason="processo não existe mais (ou é zumbi)")
        if live.starttime != session.starttime:
            return replace(session, state=ENDED, ended_at=now,
                           ended_reason="pid reutilizado por outro processo")
        if (session.state == ACTIVE
                and now - session.heartbeat_at > self.policy.heartbeat_ttl_s):
            return replace(session, state=HEARTBEAT_LOST)
        return session

    def _refresh_all(self, sessions: list[Session], now: float,
                     boot: str) -> tuple[list[Session], bool]:
        out = [self._refresh(item, now, boot) for item in sessions]
        return out, out != sessions

    def list(self, *, refresh: bool = True) -> tuple[Session, ...]:
        if not self.path.exists():
            return ()
        with self._locked():
            sessions = self._load()
            if not refresh:
                return tuple(sessions)
            now = self._clock()
            boot = self._current_boot_for_read()
            sessions, changed = self._refresh_all(sessions, now, boot)
            if changed:
                self._save(sessions)
            return tuple(sessions)

    def snapshot(self, *, refresh: bool = True) -> tuple[Session, ...]:
        """Read-only view for UI/reaper checks; never rewrites or creates state."""
        if not self.path.exists():
            return ()
        with self._locked():
            sessions = self._load()
        if not refresh:
            return tuple(sessions)
        boot = self._current_boot_for_read()
        sessions, _ = self._refresh_all(sessions, self._clock(), boot)
        return tuple(sessions)

    def _current_boot_for_read(self) -> str:
        """Leitura nunca inventa sessões se o boot_id sumiu; refresh vira no-op."""
        try:
            return self._boot()
        except SessionError:
            return ""

    # ------------------------------------------------------------------ writes

    def register(self, pid: int, *, project: str = "", label: str = "",
                 keep_active: bool = False, uid: int | None = None) -> Session:
        return self._register(pid, project=project, label=label,
                              keep_active=keep_active, uid=uid)

    def register_child(self, child, *, project: str = "", label: str = "",
                       keep_active: bool = False) -> Session:
        """Record our unreaped child even when it exited before registration.

        A zombie still has its original PID/starttime and parent. Ordinary
        registration keeps refusing zombies and processes owned by other users.
        """
        return self._register(child.pid, project=project, label=label,
                              keep_active=keep_active, allow_exited_child=True)

    def _register(self, pid: int, *, project: str = "", label: str = "",
                  keep_active: bool = False, uid: int | None = None,
                  allow_exited_child: bool = False) -> Session:
        live = procfs.read_proc(self.proc_root, int(pid))
        if live is None:
            raise SessionError(f"pid {pid} não existe; sessão não registrada")
        if live.state == "Z" and not (allow_exited_child and live.ppid == os.getpid()):
            raise SessionError(f"pid {pid} é zumbi; sessão não registrada")
        own_uid = os.getuid() if uid is None else uid
        if live.uid != own_uid:
            raise SessionError(f"pid {pid} pertence a uid {live.uid}, não a {own_uid}")
        boot = self._boot()
        now = self._clock()
        with self._locked():
            sessions = self._load()
            for item in sessions:
                if (not item.ended and item.boot_id == boot and item.pid == live.pid
                        and item.starttime == live.starttime):
                    updated = replace(
                        item, project=project or item.project,
                        label=label or item.label,
                        keep_active=item.keep_active or keep_active,
                        heartbeat_at=now, state=ACTIVE,
                        disconnected_at=None, ended_reason=None)
                    sessions[sessions.index(item)] = updated
                    self._save(sessions)
                    return updated
            cgroup = read_cgroup(live.pid, self.proc_root)
            session = Session(
                session_id=str(uuid.uuid4()), pid=live.pid,
                starttime=live.starttime, boot_id=boot, uid=live.uid,
                created_at=now, heartbeat_at=now, state=ACTIVE,
                project=project, label=label, keep_active=keep_active,
                cgroup=cgroup, cgroup_verified=cgroup is not None,
                ended_at=now if live.state == "Z" else None,
                ended_reason="filho terminou antes do registro" if live.state == "Z" else None)
            if live.state == "Z":
                session = replace(session, state=ENDED)
            sessions.append(session)
            self._save(sessions)
            return session

    def _find(self, sessions: list[Session], session_id: str) -> Session:
        for item in sessions:
            if item.session_id == session_id:
                return item
        raise SessionError(f"sessão {session_id} não encontrada")

    def heartbeat(self, session_id: str) -> Session:
        now = self._clock()
        boot = self._boot()
        with self._locked():
            sessions = self._load()
            item = self._refresh(self._find(sessions, session_id), now, boot)
            if item.ended:
                sessions[sessions.index(self._find(sessions, session_id))] = item
                self._save(sessions)
                raise SessionError(f"sessão encerrada: {item.ended_reason}")
            index = sessions.index(self._find(sessions, session_id))
            updated = replace(item, state=ACTIVE, heartbeat_at=now,
                              disconnected_at=None, ended_reason=None)
            sessions[index] = updated
            self._save(sessions)
            return updated

    def disconnect(self, session_id: str) -> Session:
        now = self._clock()
        boot = self._boot()
        with self._locked():
            sessions = self._load()
            index = sessions.index(self._find(sessions, session_id))
            item = self._refresh(sessions[index], now, boot)
            if item.ended:
                sessions[index] = item
                self._save(sessions)
                raise SessionError(f"sessão encerrada: {item.ended_reason}")
            updated = replace(item, state=DISCONNECTED, disconnected_at=now)
            sessions[index] = updated
            self._save(sessions)
            return updated

    def end(self, session_id: str, *, reason: str = "encerrada explicitamente") -> Session:
        now = self._clock()
        with self._locked():
            sessions = self._load()
            index = sessions.index(self._find(sessions, session_id))
            updated = replace(sessions[index], state=ENDED, ended_at=now,
                              ended_reason=reason)
            sessions[index] = updated
            self._save(sessions)
            return updated

    def add_artifact(self, session_id: str, path: str, *, kind: str = "file",
                     size_bytes: int | None = None,
                     ttl_days: float | None = None) -> Artifact:
        if not path or "\x00" in path or not os.path.isabs(path):
            raise SessionError("artefato exige caminho absoluto e sem NUL")
        if size_bytes is not None and (not isinstance(size_bytes, int)
                                       or size_bytes < 0):
            raise SessionError("tamanho de artefato inválido")
        now = self._clock()
        ttl = self.policy.artifact_ttl_days if ttl_days is None else float(ttl_days)
        if not math.isfinite(ttl):
            raise SessionError("vida útil de artefato inválida")
        expires = now + ttl * 86_400 if ttl > 0 else None
        artifact = Artifact(path=path, kind=kind, size_bytes=size_bytes,
                            created_at=now, expires_at=expires)
        with self._locked():
            sessions = self._load()
            index = sessions.index(self._find(sessions, session_id))
            sessions[index] = replace(
                sessions[index],
                artifacts=sessions[index].artifacts + (artifact,))
            self._save(sessions)
            return artifact

    def expired_artifacts(self, now: float | None = None) -> tuple[Artifact, ...]:
        now = self._clock() if now is None else now
        if not self.path.exists():
            return ()
        with self._locked():
            sessions = self._load()
        return tuple(
            artifact for session in sessions for artifact in session.artifacts
            if artifact.expires_at is not None and artifact.expires_at <= now)

    # --------------------------------------------------------------- protection

    def keep_active_reason(self, pid: int, starttime: int | None = None) -> str | None:
        """Reason to protect a live PID, or None. Fail closed on a bad registry.

        Read-only on purpose: this runs on every poll and from the UI, so it must
        not rewrite the registry (or create a file) just to answer a question.
        """
        if not self.path.exists():
            return None
        try:
            now = self._clock()
            boot = self._boot()
            with self._locked():
                sessions = self._load()
                sessions, _ = self._refresh_all(sessions, now, boot)
            for item in sessions:
                if item.ended or not item.keep_active:
                    continue
                if item.pid != pid:
                    continue
                if starttime is not None and item.starttime != starttime:
                    continue
                return (f"sessão {item.session_id} marcada como manter ativo "
                        f"({item.state})")
        except SessionError:
            return "registro de sessões ilegível: proteção não comprovada"
        return None

    def find_pid(self, pid: int, starttime: int | None = None) -> Session | None:
        try:
            sessions = self.snapshot()
        except SessionError:
            return None
        for item in sessions:
            if item.ended or item.pid != pid:
                continue
            if starttime is not None and item.starttime != starttime:
                continue
            return item
        return None
