"""Small, private host timeline. Called only from the resource worker."""
from __future__ import annotations

import json
import os
import re
import stat
from collections import deque
from datetime import datetime
from pathlib import Path

from .. import paths
from ..core.snapshot import OK, Snapshot

_BOOT_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_PER_BOOT_LIMIT = 4 * 1024 * 1024
_TOTAL_LIMIT = 32 * 1024 * 1024


def _sample(snapshot: Snapshot) -> dict:
    mem = snapshot.mem if snapshot.source("meminfo").status == OK else None
    pressure_mem = (snapshot.pressure_memory
                    if snapshot.source("pressure_memory").status == OK else None)
    pressure_io = (snapshot.pressure_io
                   if snapshot.source("pressure_io").status == OK else None)
    pressure_cpu = (snapshot.pressure_cpu
                    if snapshot.source("pressure_cpu").status == OK else None)
    top = None
    if snapshot.source("processes").status == OK:
        candidates = [p for p in snapshot.procs if p.cpu_frac is not None]
        if candidates:
            process = max(candidates, key=lambda p: p.cpu_frac)
            top = {"pid": process.pid, "starttime": process.starttime,
                   "name": process.comm[:80], "cpu_core_percent": round(process.cpu_frac, 1)}
    return {"boot_id": snapshot.boot_id,
            "at": datetime.fromtimestamp(snapshot.ts).astimezone().isoformat(timespec="seconds"),
            "mem_available_kb": mem.mem_available_kb if mem else None,
            "swap_used_kb": snapshot.swap_used_kb if snapshot.source("swaps").status == OK else None,
            "psi_mem_avg10": pressure_mem.some_avg10 if pressure_mem else None,
            "psi_io_avg10": pressure_io.some_avg10 if pressure_io else None,
            "psi_cpu_avg10": pressure_cpu.some_avg10 if pressure_cpu else None,
            "temperature_c": (snapshot.temperature_c
                              if snapshot.source("temperature").status == OK else None),
            "temperature_sensor": snapshot.temperature_sensor or None,
            "top_cpu": top}


class HostTimelineRecorder:
    """One short line per 15 s, fsynced at startup, once a minute or on pressure."""

    def __init__(self, directory: Path | None = None, *, interval_s: float = 15.0):
        self.directory = Path(directory) if directory else paths.host_timeline_dir()
        self.interval_s = interval_s
        self._last_mono = -float("inf")
        self._written = 0
        self.last_error = ""

    def record(self, snapshot: Snapshot) -> None:
        if not _BOOT_ID.fullmatch(snapshot.boot_id or ""):
            self.last_error = "boot ID ausente ou inválido"
            return
        if snapshot.mono - self._last_mono < self.interval_s:
            return
        try:
            if self.directory.is_symlink():
                raise ValueError("diretório de histórico é link simbólico")
            self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            dir_info = self.directory.stat()
            if (not stat.S_ISDIR(dir_info.st_mode) or dir_info.st_uid != os.getuid()
                    or stat.S_IMODE(dir_info.st_mode) != 0o700):
                raise ValueError("diretório de histórico não é privado")
            entries = list(self.directory.iterdir())
            if len(entries) > 64:
                raise ValueError("mais de 64 arquivos de histórico; revisão necessária")
            size = 0
            for entry in entries:
                if entry.is_symlink() or not entry.is_file():
                    raise ValueError("entrada de histórico inesperada")
                size += entry.stat().st_size
            if size >= _TOTAL_LIMIT:
                raise ValueError("limite de 32 MiB de histórico alcançado")
            path = self.directory / f"{snapshot.boot_id}.jsonl"
            item = _sample(snapshot)
            raw = (json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) != 0o600
                        or info.st_size + len(raw) > _PER_BOOT_LIMIT):
                    raise ValueError("arquivo de histórico não é privado ou está cheio")
                with os.fdopen(fd, "ab", closefd=False) as stream:
                    stream.write(raw)
                    stream.flush()
                pressure = ((item["psi_mem_avg10"] or 0) >= 5
                            or (item["psi_io_avg10"] or 0) >= 5)
                if self._written % 4 == 0 or pressure:
                    os.fsync(fd)
            finally:
                os.close(fd)
        except (OSError, ValueError) as exc:
            self.last_error = str(exc)
            return
        self._last_mono = snapshot.mono
        self._written += 1
        self.last_error = ""


def _valid_sample(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    boot_id, at = row.get("boot_id"), row.get("at")
    if not isinstance(boot_id, str) or not _BOOT_ID.fullmatch(boot_id):
        return False
    if not isinstance(at, str):
        return False
    try:
        stamp = datetime.fromisoformat(at)
    except ValueError:
        return False
    return stamp.tzinfo is not None


def read_timeline(directory: Path | None = None, *, limit: int = 80,
                  boot_id: str | None = None) -> dict:
    """Read the most recent bounded samples; unknown data is never zero."""
    folder = Path(directory) if directory else paths.host_timeline_dir()
    try:
        if boot_id is not None and not _BOOT_ID.fullmatch(boot_id):
            raise ValueError("boot ID inválido")
        if folder.is_symlink() or not folder.is_dir():
            return {"quality": "missing", "reason": "histórico ausente", "samples": []}
        info = folder.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("diretório de histórico não é privado")
        entries = list(folder.iterdir())
        if len(entries) > 64 or any(p.is_symlink() or not p.is_file() for p in entries):
            raise ValueError("inventário de histórico inválido")
        files = [p for p in entries if p.name.endswith(".jsonl")]
        if boot_id is not None:
            files = [p for p in files if p.name == f"{boot_id}.jsonl"]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        recent = deque(maxlen=max(1, min(limit, 200)))
        malformed = 0
        for path in reversed(files[:2] if boot_id is None else files):
            info = path.stat()
            if (info.st_size > _PER_BOOT_LIMIT or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError("arquivo de histórico fora do limite ou não privado")
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        malformed += 1
                        continue
                    if not _valid_sample(row):
                        malformed += 1
                        continue
                    recent.append(row)
        samples = list(recent)
        quality = "partial" if malformed else "ok" if samples else "missing"
        reason = (f"{malformed} amostra(s) ilegível(is) preservada(s)" if malformed
                  else "" if samples else "histórico vazio")
        return {"quality": quality, "reason": reason, "samples": samples}
    except (OSError, ValueError, UnicodeError, TypeError) as exc:
        return {"quality": "unknown", "reason": str(exc), "samples": []}
