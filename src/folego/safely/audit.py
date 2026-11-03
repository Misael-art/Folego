"""Append-only audit trail (JSONL). Every mutation, refusal and failure lands here.

One record per line, fsynced before append returns: even if the app (or the
Deck) dies right after an action, the trail of what was attempted survives.

The active file is bounded: when it reaches ``max_bytes`` the next append (or an
explicit ``folego logs rotate``) moves it to a gzip archive and starts a fresh
file. Archives are never silently deleted — an ``audit_event_id`` in the tmpfs
ledger must stay resolvable. Rotation and append share a sidecar ``flock``, so a
rotation cannot swallow a concurrent record.
"""
from __future__ import annotations

import contextlib
import fcntl
import gzip
import json
import os
import time
import uuid
from pathlib import Path

from .. import paths
from .atomicfile import write_atomic

AUDIT_MAX_BYTES = 32 * 1024 * 1024
AUDIT_ARCHIVE_MAX_BYTES = 256 * 1024 * 1024


class AuditLog:
    def __init__(self, path: Path | None = None, *,
                 max_bytes: int = AUDIT_MAX_BYTES,
                 archive_max_bytes: int = AUDIT_ARCHIVE_MAX_BYTES):
        self.path = Path(path) if path else paths.audit_log_path()
        self.max_bytes = max(1, int(max_bytes))
        self.archive_max_bytes = max(1, int(archive_max_bytes))

    @contextlib.contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.path.with_name(self.path.name + ".lock")
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def append(self, *, kind: str, action_id: str = "", outcome: str = "",
               targets: list[str] | None = None, risk: str | None = None,
               backup_id: str | None = None, plan_digest: str | None = None,
               error: str | None = None, duration_ms: int | None = None,
               actor: str = "user-confirm") -> dict:
        for field, value in (("kind", kind), ("action_id", action_id),
                             ("outcome", outcome)):
            if not value:
                raise ValueError(f"audit record requires non-empty {field}")
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event_id": uuid.uuid4().hex,
            "kind": kind,
            "action_id": action_id,
            "outcome": outcome,
            "actor": actor,
            "targets": targets or [],
            "risk": risk,
            "backup_id": backup_id,
            "plan_digest": plan_digest,
            "error": error,
            "duration_ms": duration_ms,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._locked():
            # Rotação é manutenção, não pré-condição do registro: se compactar
            # falhar, o evento ainda é anexado ao arquivo ativo (nada se perde).
            try:
                if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                    self._rotate_locked()
            except OSError:
                pass
            if not self.path.exists():
                write_atomic(self.path, line.encode(), mode=0o600)
                return record
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, line.encode())
                os.fsync(fd)
            finally:
                os.close(fd)
        return record

    # ------------------------------------------------------------------ rotação

    def rotate(self, *, now: float | None = None) -> dict:
        """Move the active file to a gzip archive and return what changed."""
        with self._locked():
            before = self.path.stat().st_size if self.path.exists() else 0
            archive = self._rotate_locked(now=now)
        return {"rotated": archive is not None, "active_bytes_before": before,
                "archive": str(archive) if archive else None,
                "active_bytes_after": (self.path.stat().st_size
                                       if self.path.exists() else 0)}

    def _rotate_locked(self, *, now: float | None = None) -> Path | None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        stamp = time.strftime("%Y%m%dT%H%M%SZ",
                              time.gmtime(time.time() if now is None else now))
        archive = self.path.with_name(f"{self.path.stem}-{stamp}.jsonl.gz")
        suffix = 1
        while archive.exists():
            archive = self.path.with_name(
                f"{self.path.stem}-{stamp}-{suffix}.jsonl.gz")
            suffix += 1
        temp = archive.with_name(archive.name + f".tmp-{os.getpid()}")
        try:
            with self.path.open("rb") as source, gzip.open(temp, "wb") as target:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp, archive)
            # A cópia durável já existe; truncar é o segundo passo. Se ele falhar,
            # os mesmos registros aparecem no ativo e no arquivo — duplicar é
            # menos grave que perder auditoria.
            fd = os.open(self.path, os.O_WRONLY | os.O_TRUNC | os.O_CREAT, 0o600)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
        return archive

    def status(self) -> dict:
        active = self.path.stat().st_size if self.path.exists() else 0
        archives = []
        parent = self.path.parent
        if parent.exists():
            for candidate in sorted(parent.glob(f"{self.path.stem}-*.jsonl.gz")):
                try:
                    archives.append({"path": str(candidate),
                                     "bytes": candidate.stat().st_size})
                except OSError:
                    continue
        archive_bytes = sum(item["bytes"] for item in archives)
        return {
            "active_bytes": active,
            "active_over_budget": active > self.max_bytes,
            "archive_count": len(archives),
            "archive_bytes": archive_bytes,
            "archive_over_budget": archive_bytes > self.archive_max_bytes,
            "archives": archives,
            "max_bytes": self.max_bytes,
            "archive_max_bytes": self.archive_max_bytes,
        }

    def archived_records(self) -> list[dict]:
        """All records in active + archives, oldest archive first."""
        records: list[dict] = []
        parent = self.path.parent
        paths = (sorted(parent.glob(f"{self.path.stem}-*.jsonl.gz"))
                 if parent.exists() else [])
        if self.path.exists():
            paths.append(self.path)
        for path in paths:
            try:
                opener = gzip.open if path.suffix == ".gz" else open
                with opener(path, "rt", encoding="utf-8") as handle:
                    for raw in handle:
                        try:
                            row = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(row, dict):
                            records.append(row)
            except OSError:
                continue
        return records

    def tail(self, n: int) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for raw in lines[-max(n, 0) * 4:]:  # janela limitada; linha corrupta é pulada
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            out.append(rec)
        return out[-n:]
