"""One-way, non-destructive state migration from DeckWellness to Fôlego (F8).

The legacy tree is never deleted or renamed. Existing Fôlego files are never
overwritten: conflicts go to ``migrated/deckwellness-<stamp>``. A marker is
written before the first copy; an interrupted migration is therefore unknown,
not silently retried, and the user can inspect both trees.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import paths
from ..safely.atomicfile import write_atomic

MARKER_NAME = "migration.json"


class MigrationError(Exception):
    pass


@dataclass(frozen=True)
class MigrationEntry:
    kind: str
    source: Path
    destination: Path
    files: int = 0
    bytes: int = 0
    status: str = "pronto"
    errors: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == "pronto"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "source": str(self.source),
                "destination": str(self.destination), "files": self.files,
                "bytes": self.bytes, "status": self.status,
                "errors": list(self.errors)}


@dataclass(frozen=True)
class MigrationPlan:
    entries: tuple[MigrationEntry, ...]
    marker: Path
    stamp: str

    @property
    def ready(self) -> bool:
        return bool(self.entries) and all(entry.ready for entry in self.entries)

    @property
    def conflicts(self) -> tuple[MigrationEntry, ...]:
        return tuple(entry for entry in self.entries if not entry.ready)

    def to_dict(self) -> dict:
        return {"entries": [entry.to_dict() for entry in self.entries],
                "ready": self.ready, "conflicts": len(self.conflicts),
                "marker": str(self.marker), "stamp": self.stamp}


def default_roots() -> list[tuple[str, Path, Path]]:
    home = Path.home()
    state_home = paths._env_dir("XDG_STATE_HOME", home / ".local" / "state")
    data_home = paths._env_dir("XDG_DATA_HOME", home / ".local" / "share")
    return [
        ("state", state_home / "deckwellness", paths.state_dir()),
        ("config", paths.xdg_config_home() / "deckwellness", paths.config_dir()),
        ("data", data_home / "deckwellness", paths.data_dir()),
    ]


def _scan(source: Path) -> tuple[int, int, list[str]]:
    files = total = 0
    errors = []
    for current, dirs, names in os.walk(source, followlinks=False):
        current_path = Path(current)
        for name in list(dirs):
            candidate = current_path / name
            if candidate.is_symlink():
                errors.append(f"link simbólico não migrado: {candidate}")
                dirs.remove(name)
        for name in names:
            candidate = current_path / name
            if candidate.is_symlink():
                errors.append(f"link simbólico não migrado: {candidate}")
                continue
            try:
                stat = candidate.lstat()
            except OSError as exc:
                errors.append(f"ilegível: {candidate}: {exc}")
                continue
            if not candidate.is_file():
                errors.append(f"tipo não migrado: {candidate}")
                continue
            files += 1
            total += max(0, stat.st_size)
    return files, total, errors


def build_plan(roots=None, *, clock=None, marker: Path | None = None,
               stamp: str | None = None) -> MigrationPlan:
    stamp = stamp or time.strftime(
        "%Y%m%dT%H%M%SZ", time.gmtime(time.time() if clock is None else clock))
    roots = default_roots() if roots is None else roots
    entries = []
    for kind, source, destination in roots:
        source = Path(source)
        destination = Path(destination)
        if not source.exists():
            continue
        files, total, errors = _scan(source)
        if errors:
            entries.append(MigrationEntry(kind, source, destination, files, total,
                                          "conflito", tuple(errors)))
            continue
        target = destination
        if destination.exists() and any(destination.iterdir()):
            target = destination / "migrated" / f"deckwellness-{stamp}"
        entries.append(MigrationEntry(kind, source, target, files, total, "pronto"))
    marker = Path(marker) if marker else paths.state_dir() / MARKER_NAME
    return MigrationPlan(tuple(entries), marker, stamp)


def _write_marker(marker: Path, plan: MigrationPlan, status: str, detail: str = ""):
    marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps({"version": 1, "status": status, "stamp": plan.stamp,
                          "detail": detail, "plan": plan.to_dict()},
                         ensure_ascii=False, sort_keys=True).encode("utf-8")
    write_atomic(marker, payload, mode=0o600)


def apply_plan(plan: MigrationPlan, *, confirm: bool = False) -> MigrationPlan:
    if not confirm:
        raise MigrationError("migração exige confirmação explícita")
    if not plan.ready:
        raise MigrationError("plano tem conflito; nada foi copiado")
    if plan.marker.exists():
        try:
            old = json.loads(plan.marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MigrationError(
                f"marcador de migração ilegível ({exc}); não há como provar o "
                "estado anterior") from exc
        if old.get("status") == "completed":
            raise MigrationError("migração já concluída; nada foi repetido")
        raise MigrationError(
            "migração anterior sem resultado completo; inspecione as duas "
            "árvores e o marcador antes de continuar")
    _write_marker(plan.marker, plan, "started")
    for entry in plan.entries:
        try:
            for current, _dirs, names in os.walk(entry.source, followlinks=False):
                relative = Path(current).relative_to(entry.source)
                target_dir = entry.destination / relative
                target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                for name in names:
                    source_file = Path(current) / name
                    if source_file.is_symlink():
                        raise MigrationError(
                            f"link apareceu durante a cópia: {source_file}")
                    target_file = target_dir / name
                    if target_file.exists():
                        raise MigrationError(
                            f"destino ocupado durante a cópia: {target_file}")
                    shutil.copy2(source_file, target_file, follow_symlinks=False)
        except (OSError, MigrationError) as exc:
            _write_marker(plan.marker, plan, "failed", str(exc))
            raise MigrationError(
                f"migração interrompida: {exc}; origem preservada, destino "
                "parcial identificado pelo marcador") from exc
    _write_marker(plan.marker, plan, "completed")
    return plan
