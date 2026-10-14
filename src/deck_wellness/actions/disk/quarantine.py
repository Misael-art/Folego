"""Disk hygiene M5 — reversible reclamation.

Deleting user data is never the first step. `move_in` renames a tree into the
app's quarantine directory on the *same* filesystem (atomic, zero-copy, fully
revertible); `purge` is a separate, explicit decision. The manifest is written
before the rename so an interrupted move can be repaired by `reconcile`.
"""
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ... import paths
from ...safely import guard
from ...safely.audit import AuditLog
from ...safely.atomicfile import write_atomic
from .measure import measure_tree

STATE_PLANNED = "planned"
STATE_STORED = "stored"
STATE_RESTORED = "restored"
STATE_PURGED = "purged"


@dataclass(frozen=True)
class QuarantineEntry:
    entry_id: str
    original: str
    stored: str
    bytes: int
    state: str
    moved_at: str
    action_id: str

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id, "original": self.original, "stored": self.stored,
            "bytes": self.bytes, "state": self.state, "moved_at": self.moved_at,
            "action_id": self.action_id,
        }


@dataclass(frozen=True)
class ActionResult:
    entry_id: str
    ok: bool
    reason: str


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _under(path_str: str, root: str) -> bool:
    return path_str == root or path_str.startswith(root + os.sep)


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:60] or "unnamed"


class Quarantine:
    def __init__(self, root: Path | None = None, *, allowed_roots=None,
                 audit: AuditLog | None = None, stat_fn=os.stat):
        self.root = Path(root) if root else paths.data_dir() / "quarantine"
        self.allowed_roots = list(allowed_roots) if allowed_roots else [Path.home()]
        self.audit = audit
        self.stat_fn = stat_fn

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def entries(self) -> dict:
        raw = self._read()
        return {r["entry_id"]: QuarantineEntry(**r) for r in raw}

    def _read(self) -> list:
        if not self.manifest_path.exists():
            return []
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    def _write(self, rows: list) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        write_atomic(self.manifest_path,
                     json.dumps(rows, ensure_ascii=False, indent=1).encode())
        os.chmod(self.manifest_path, 0o600)

    def _update(self, entry_id: str, **changes) -> QuarantineEntry:
        rows = self._read()
        found = None
        for row in rows:
            if row["entry_id"] == entry_id:
                row.update(changes)
                found = row
        self._write(rows)
        return QuarantineEntry(**found)

    def _audit(self, kind: str, entry_id: str, outcome: str, targets: list[str],
               error: str | None = None) -> None:
        if self.audit is None:
            return
        self.audit.append(kind=kind, action_id=entry_id, outcome=outcome,
                          targets=targets, risk="reversible" if outcome != "purged"
                          else "irreversible", error=error)

    def _check(self, p: Path) -> None:
        verdict = guard.validate_target(p, self.allowed_roots)
        if not verdict.ok:
            raise PermissionError(verdict.reason)

    def move_in(self, path, *, action_id: str = "disk.quarantine") -> QuarantineEntry:
        p = Path(os.path.expanduser(str(path)))
        self._check(p)
        if not p.exists():
            raise PermissionError(f"refused: nothing to quarantine at {p}")
        root_resolved = str(self.root.resolve())
        if _under(str(p.resolve()), root_resolved) or str(p.resolve()) == root_resolved:
            raise PermissionError("refused: path is already inside the quarantine root")

        self.root.mkdir(parents=True, exist_ok=True)
        if self.stat_fn(p).st_dev != self.stat_fn(self.root).st_dev:
            raise PermissionError(
                f"refused: cross-device move for {p} would be a copy, not a rename")

        stat = measure_tree(p)
        entry_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        stored = self.root / f"{_sanitize(p.name)}-{entry_id}"
        entry = QuarantineEntry(entry_id, str(p), str(stored), stat.bytes,
                                STATE_PLANNED, "", action_id)
        rows = self._read()
        rows.append(entry.to_dict())
        self._write(rows)

        os.rename(p, stored)
        moved = self._update(entry_id, state=STATE_STORED, moved_at=_now())
        self._audit("disk.quarantine", entry_id, STATE_STORED, [str(p), str(stored)])
        return moved

    def restore(self, entry_id: str) -> ActionResult:
        entry = self.entries().get(entry_id)
        if entry is None:
            return ActionResult(entry_id, False, "refused: unknown quarantine entry")
        if entry.state != STATE_STORED:
            return ActionResult(entry_id, False, f"refused: entry is {entry.state}")
        original = Path(entry.original)
        if original.exists():
            return ActionResult(entry_id, False,
                                "refused: original path already exists, nothing overwritten")
        verdict = guard.validate_target(original, self.allowed_roots)
        if not verdict.ok:
            return ActionResult(entry_id, False, verdict.reason)
        if not Path(entry.stored).exists():
            return ActionResult(entry_id, False, "refused: stored payload is missing")

        os.rename(entry.stored, original)
        self._update(entry_id, state=STATE_RESTORED, moved_at=_now())
        self._audit("disk.restore", entry_id, STATE_RESTORED,
                    [entry.stored, entry.original])
        return ActionResult(entry_id, True, "ok")

    def purge(self, entry_id: str) -> ActionResult:
        entry = self.entries().get(entry_id)
        if entry is None:
            return ActionResult(entry_id, False, "refused: unknown quarantine entry")
        if entry.state != STATE_STORED:
            return ActionResult(entry_id, False, f"refused: entry is already {entry.state}")
        self._check(Path(entry.stored))

        shutil.rmtree(entry.stored)
        self._update(entry_id, state=STATE_PURGED, moved_at=_now())
        self._audit("disk.purge", entry_id, STATE_PURGED, [entry.stored])
        return ActionResult(entry_id, True, "ok")

    def reclaimable_bytes(self) -> int:
        return sum(e.bytes for e in self.entries().values() if e.state == STATE_STORED)

    def reconcile(self) -> list:
        """Close the crash window between 'planned' and the rename finishing."""
        rows = self._read()
        repaired = []
        for row in rows:
            if row["state"] != STATE_PLANNED:
                continue
            if not Path(row["original"]).exists() and Path(row["stored"]).exists():
                row["state"] = STATE_STORED
                row["moved_at"] = _now()
                repaired.append(row["entry_id"])
        if repaired:
            self._write(rows)
            for entry_id in repaired:
                self._audit("disk.reconcile", entry_id, STATE_STORED, [])
        return repaired
