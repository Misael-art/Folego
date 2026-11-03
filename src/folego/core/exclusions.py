"""User exclusions by app/project/session/cmdline, with an explicit keep-alive flag.

This is a small, private, versioned file. A missing file means "no exclusions";
a corrupt file raises and callers must fail closed (show nothing as terminable)
rather than silently dropping a protection. "keep_active" is stronger than a
plain exclusion: the identity is also protected at act time, not only filtered
out of the list.
"""
import contextlib
import fcntl
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from ..safely.atomicfile import write_atomic

SCHEMA_VERSION = 1
KINDS = ("app", "project", "session", "cmdline", "path")


class ExclusionError(Exception):
    pass


@dataclass(frozen=True)
class Exclusion:
    exclusion_id: str
    kind: str
    value: str
    keep_active: bool = False
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {"exclusion_id": self.exclusion_id, "kind": self.kind,
                "value": self.value, "keep_active": self.keep_active,
                "created_at": self.created_at}

    @classmethod
    def from_dict(cls, data: dict) -> "Exclusion":
        try:
            exclusion_id = str(uuid.UUID(str(data["exclusion_id"])))
            kind = str(data["kind"])
            value = str(data["value"])
            created_at = float(data.get("created_at", 0.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ExclusionError(f"exclusão inválida: {exc}") from exc
        if kind not in KINDS:
            raise ExclusionError(f"tipo de exclusão desconhecido: {kind!r}")
        if not value:
            raise ExclusionError("exclusão sem valor")
        return cls(exclusion_id, kind, value,
                   bool(data.get("keep_active", False)), created_at)


def _basename(command: str) -> str:
    return command.rsplit("/", 1)[-1]


class ExclusionList:
    def __init__(self, path: Path | str | None = None, *, clock=time.time):
        self.path = Path(path) if path else paths.exclusions_path()
        self._clock = clock
        self._lock_path = self.path.with_name(self.path.name + ".lock")

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

    def _load(self) -> list[Exclusion]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError) as exc:
            raise ExclusionError(f"lista de exclusões ilegível: {exc}") from exc
        if not isinstance(raw, dict):
            raise ExclusionError("lista de exclusões não é um objeto")
        if raw.get("version") != SCHEMA_VERSION:
            raise ExclusionError(f"versão de exclusões não suportada: "
                                 f"{raw.get('version')!r}")
        items = raw.get("exclusions")
        if not isinstance(items, list):
            raise ExclusionError("campo exclusions inválido")
        return [Exclusion.from_dict(item) for item in items]

    def _save(self, items: list[Exclusion]) -> None:
        payload = json.dumps(
            {"version": SCHEMA_VERSION,
             "exclusions": [item.to_dict() for item in items]},
            ensure_ascii=False, sort_keys=True).encode("utf-8")
        try:
            write_atomic(self.path, payload, mode=0o600)
        except OSError as exc:
            raise ExclusionError(f"não foi possível gravar as exclusões: {exc}") from exc

    def list(self) -> tuple[Exclusion, ...]:
        if not self.path.exists():
            return ()
        with self._locked():
            return tuple(self._load())

    def add(self, kind: str, value: str, *, keep_active: bool = False) -> Exclusion:
        kind = str(kind).strip().lower()
        value = str(value).strip()
        if kind not in KINDS:
            raise ExclusionError(f"tipo de exclusão desconhecido: {kind!r}")
        if not value or "\x00" in value:
            raise ExclusionError("exclusão exige valor não vazio")
        item = Exclusion(str(uuid.uuid4()), kind, value, keep_active,
                         self._clock())
        with self._locked():
            items = self._load()
            items.append(item)
            self._save(items)
        return item

    def remove(self, exclusion_id: str) -> bool:
        if not self.path.exists():
            return False
        with self._locked():
            items = self._load()
            kept = [item for item in items if item.exclusion_id != exclusion_id]
            if len(kept) == len(items):
                return False
            self._save(kept)
            return True

    @staticmethod
    def _match(item: Exclusion, proc, project: str, session_id: str) -> bool:
        needle = item.value.casefold()
        if item.kind == "app":
            names = {proc.comm.casefold()}
            if proc.cmdline:
                names.add(_basename(proc.cmdline[0]).casefold())
            return needle in names
        if item.kind == "project":
            return bool(project) and project.casefold() == needle
        if item.kind == "session":
            return bool(session_id) and session_id == item.value
        if item.kind == "cmdline":
            return needle in " ".join(proc.cmdline).casefold()
        if item.kind == "path":
            prefix = item.value.rstrip("/") + "/"
            return any(arg == item.value or arg.startswith(prefix)
                       for arg in proc.cmdline)
        return False

    def reason(self, proc, *, project: str = "",
               session_id: str = "") -> str | None:
        """Motivo de exclusão/proteção, ou None. Arquivo ilegível falha fechado."""
        try:
            items = self.list()
        except ExclusionError as exc:
            return f"exclusões ilegíveis: {exc}"
        for item in items:
            if self._match(item, proc, project, session_id):
                label = item.value
                suffix = " (manter ativo)" if item.keep_active else ""
                return f"exclusão {item.kind}:{label}{suffix}"
        return None
