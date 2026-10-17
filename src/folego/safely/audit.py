"""Append-only audit trail (JSONL). Every mutation, refusal and failure lands here.

One record per line, fsynced before append returns: even if the app (or the
Deck) dies right after an action, the trail of what was attempted survives.
"""
import json
import os
import time
import uuid
from pathlib import Path

from .. import paths
from .atomicfile import write_atomic


class AuditLog:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.audit_log_path()

    def append(self, *, kind: str, action_id: str = "", outcome: str = "",
               targets: list[str] | None = None, risk: str | None = None,
               backup_id: str | None = None, plan_digest: str | None = None,
               error: str | None = None, duration_ms: int | None = None,
               actor: str = "user-confirm") -> dict:
        for field, value in (("kind", kind), ("action_id", action_id), ("outcome", outcome)):
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            write_atomic(self.path, line.encode())
            os.chmod(self.path, 0o600)
            return record
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        return record

    def tail(self, n: int) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for raw in lines[-max(n, 0) * 4:]:  # bounded window; corrupt lines skipped below
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            out.append(rec)
        return out[-n:]
