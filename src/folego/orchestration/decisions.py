"""Persistent review trail for F6 simulations ("executaria", never executed).

The policy is pure: ``automation.evaluate`` returns a decision and touches
nothing. This module is the only place a simulation becomes durable. A record
always carries ``executed: false`` and the plan digest, so a later human review
can compare what the policy wanted with what was actually done. There is no API
here that performs the plan.

The active file is compacted into ``.jsonl.gz`` archives on the same budget
model as the audit trail; archives are never deleted automatically.
"""
from __future__ import annotations

import contextlib
import fcntl
import gzip
import json
import os
import time
import uuid
from collections import deque
from pathlib import Path

from .. import paths
from ..safely.atomicfile import write_atomic
from .automation import SIMULAR

SCHEMA_VERSION = 1
ACTOR = "automation-simulacao"
DECISION_MAX_BYTES = 4 * 1024 * 1024


class DecisionLog:
    def __init__(self, path: Path | None = None, *, clock=None,
                 max_bytes: int = DECISION_MAX_BYTES):
        self.path = Path(path) if path else paths.automation_decisions_path()
        self._clock = clock or time.time
        self.max_bytes = max(1, int(max_bytes))

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

    def record(self, decision, *, mode: str, preset: str,
               actor: str = ACTOR, now: float | None = None) -> dict | None:
        """Persist a would-execute simulation decision; return ``None`` otherwise.

        Refusals/waiting decisions are deliberately not written here: the review
        queue is about what *would* have happened, and a refusal has no effect to
        compare. The pure decision remains available to callers/loggers.
        """
        if decision.kind != SIMULAR:
            return None
        plan = decision.plan
        action = getattr(plan, "action", "")
        target = getattr(plan, "target", None)
        target_payload = (target.to_dict() if hasattr(target, "to_dict")
                          else {"kind": "unknown", "key": str(target or "")})
        timestamp = self._clock() if now is None else now
        record = {
            "schema": SCHEMA_VERSION,
            "event_id": uuid.uuid4().hex,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp)),
            "actor": actor,
            "mode": str(mode),
            "preset": str(preset),
            "decision": str(decision.kind),
            "would_execute": True,
            "executed": False,
            "action": str(action),
            "target": target_payload,
            "plan_digest": getattr(plan, "digest", ""),
            "reason": decision.reason,
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        with self._locked():
            try:
                if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                    self._rotate_locked(now=timestamp)
            except OSError:
                pass
            if not self.path.exists():
                write_atomic(self.path, line.encode(), mode=0o600)
            else:
                fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                             0o600)
                try:
                    os.write(fd, line.encode())
                    os.fsync(fd)
                finally:
                    os.close(fd)
        return record

    def _archives(self) -> list[Path]:
        if not self.path.parent.exists():
            return []
        return sorted(self.path.parent.glob(f"{self.path.stem}-*.jsonl.gz"))

    def _rotate_locked(self, *, now: float | None = None) -> Path | None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        stamp = time.strftime(
            "%Y%m%dT%H%M%SZ",
            time.gmtime(self._clock() if now is None else now))
        archive = self.path.with_name(f"{self.path.stem}-{stamp}.jsonl.gz")
        suffix = 1
        while archive.exists():
            archive = self.path.with_name(
                f"{self.path.stem}-{stamp}-{suffix}.jsonl.gz")
            suffix += 1
        temp = archive.with_name(archive.name + f".tmp-{os.getpid()}")
        try:
            with self.path.open("rb") as source, gzip.open(temp, "wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp, archive)
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

    def recent(self, limit: int = 20) -> list[dict]:
        """Newest ``limit`` records, oldest-first, reading archives + active."""
        limit = max(0, int(limit))
        if limit == 0:
            return []
        records: deque[dict] = deque(maxlen=limit)
        paths = self._archives()
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
                        if isinstance(row, dict) and row.get("schema") == SCHEMA_VERSION:
                            records.append(row)
            except OSError:
                continue
        return list(records)

    def status(self) -> dict:
        active = self.path.stat().st_size if self.path.exists() else 0
        archives = []
        for path in self._archives():
            try:
                archives.append({"path": str(path), "bytes": path.stat().st_size})
            except OSError:
                continue
        return {"active_bytes": active, "archive_count": len(archives),
                "archive_bytes": sum(item["bytes"] for item in archives),
                "max_bytes": self.max_bytes}
