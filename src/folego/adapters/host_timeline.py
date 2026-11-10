"""Small, private host timeline. Called only from the resource worker."""
from __future__ import annotations

import json
import math
import os
import re
import stat
from collections import deque
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .. import paths
from ..core.battery_alerts import voltage_level
from ..core.snapshot import ERROR, MISSING, OK, PARTIAL, Snapshot, SourceQuality
from ..safely.atomicfile import fsync_dir

_BOOT_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_PER_BOOT_LIMIT = 4 * 1024 * 1024
_TOTAL_LIMIT = 32 * 1024 * 1024
_CAPACITY_WARNING_PERCENT = 85
_SOURCES = ("meminfo", "swaps", "pressure_memory", "pressure_io", "pressure_cpu",
            "temperature", "battery", "external_power", "processes")
POWER_EVENT_LABELS = {
    "battery-voltage-critical": "queda crítica de tensão da bateria",
    "external-power-connected": "alimentação externa conectada",
    "external-power-disconnected": "alimentação externa desconectada",
}


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
    battery = snapshot.battery if snapshot.source("battery").status == OK else None
    issues = {}
    for name in _SOURCES:
        status = snapshot.source(name).status
        if status != OK:
            issues[name] = status
    return {"schema": 2, "boot_id": snapshot.boot_id,
            "at": datetime.fromtimestamp(snapshot.ts).astimezone().isoformat(timespec="milliseconds"),
            "mono_ns": (round(snapshot.mono * 1_000_000_000)
                        if math.isfinite(snapshot.mono) and snapshot.mono > 0 else None),
            "collector_read_ms": (round(snapshot.duration_s * 1000, 2)
                                  if math.isfinite(snapshot.duration_s) and snapshot.duration_s > 0 else None),
            # Sparse: in schema 2, an unlisted source is OK. Old schema has
            # no quality proof at all. This saves space at the fixed 4 MiB cap.
            "source_issues": issues,
            "mem_available_kb": mem.mem_available_kb if mem else None,
            "swap_used_kb": snapshot.swap_used_kb if snapshot.source("swaps").status == OK else None,
            "psi_mem_avg10": pressure_mem.some_avg10 if pressure_mem else None,
            "psi_mem_avg60": pressure_mem.some_avg60 if pressure_mem else None,
            "psi_io_avg10": pressure_io.some_avg10 if pressure_io else None,
            "psi_io_avg60": pressure_io.some_avg60 if pressure_io else None,
            "psi_cpu_avg10": pressure_cpu.some_avg10 if pressure_cpu else None,
            "psi_cpu_avg60": pressure_cpu.some_avg60 if pressure_cpu else None,
            "temperature_c": (snapshot.temperature_c
                              if snapshot.source("temperature").status == OK else None),
            "temperature_sensor": ((snapshot.temperature_sensor or None)
                                   if snapshot.source("temperature").status == OK else None),
            "battery_percent": battery.percent if battery else None,
            "battery_status": battery.status if battery else None,
            "battery_voltage_uv": battery.voltage_uv if battery else None,
            "battery_voltage_min_design_uv": battery.voltage_min_design_uv if battery else None,
            "battery_current_ua": battery.current_ua if battery else None,
            "battery_power_uw": battery.power_uw if battery else None,
            "external_power_online": (snapshot.external_power_online
                                      if snapshot.source("external_power").status == OK else None),
            "top_cpu": top}


class HostTimelineRecorder:
    """Record power events durably on observation, with a 15 s normal cadence."""

    def __init__(self, directory: Path | None = None, *, interval_s: float = 15.0):
        self.directory = Path(directory) if directory else paths.host_timeline_dir()
        self.interval_s = interval_s
        self._boot_id = None
        self._last_mono = -float("inf")
        self._written = 0
        self._last_external_power = None
        self._voltage_critical = False
        self.last_error = ""

    def record(self, snapshot: Snapshot) -> None:
        if not _BOOT_ID.fullmatch(snapshot.boot_id or ""):
            self.last_error = "boot ID ausente ou inválido"
            return
        if snapshot.boot_id != self._boot_id:
            self._boot_id = snapshot.boot_id
            self._last_mono = -float("inf")
            self._written = 0
            self._last_external_power = None
            self._voltage_critical = False
        battery = snapshot.battery if snapshot.source("battery").status == OK else None
        level = voltage_level(battery)
        online = (snapshot.external_power_online
                  if snapshot.source("external_power").status == OK else None)
        events = []
        critical = self._voltage_critical
        if level == "critical":
            if not critical:
                events.append("battery-voltage-critical")
            critical = True
        elif (level in ("acceptable", "stable")
              or (online is True and battery and battery.status in ("Charging", "Full"))):
            critical = False
        if online is not None and self._last_external_power is not None and online != self._last_external_power:
            events.append("external-power-connected" if online else "external-power-disconnected")
        if not events and snapshot.mono - self._last_mono < self.interval_s:
            self._remember_power(online, critical)
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
            path = self.directory / f"{snapshot.boot_id}.jsonl"
            item = _sample(snapshot)
            if events:
                item["power_events"] = events
            raw = (json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
            if size + len(raw) > _TOTAL_LIMIT:
                raise ValueError("limite de 32 MiB de histórico alcançado")
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
                if self._written % 4 == 0 or pressure or events:
                    os.fsync(fd)
                    if self._written == 0:
                        fsync_dir(self.directory)
            finally:
                os.close(fd)
        except (OSError, ValueError) as exc:
            self.last_error = str(exc)
            return
        self._last_mono = snapshot.mono
        self._written += 1
        self._remember_power(online, critical)
        self.last_error = ""

    def _remember_power(self, online: bool | None, critical: bool) -> None:
        if online is not None:
            self._last_external_power = online
        self._voltage_critical = critical


def record_snapshot(recorder: HostTimelineRecorder, snapshot: Snapshot) -> Snapshot:
    """Expose recorder failure to the normal resource UI without hiding metrics."""
    recorder.record(snapshot)
    quality = SourceQuality("host_timeline", ERROR if recorder.last_error else OK,
                            recorder.last_error, snapshot.mono)
    return replace(snapshot, sources=snapshot.sources + (quality,))


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
    if stamp.tzinfo is None:
        return False
    schema = row.get("schema", 1)
    if schema == 1:
        return True  # historical lines predate source quality and monotonic time
    if schema != 2:
        return False
    statuses = row.get("source_issues")
    if (not isinstance(statuses, dict) or not set(statuses) <= set(_SOURCES)
            or any(value not in (PARTIAL, MISSING, ERROR)
                   for value in statuses.values())):
        return False
    mono_ns = row.get("mono_ns")
    if mono_ns is not None and (type(mono_ns) is not int or mono_ns <= 0):
        return False
    for name in ("battery_voltage_uv", "battery_voltage_min_design_uv",
                 "battery_current_ua", "battery_power_uw"):
        value = row.get(name)
        if value is not None and (type(value) is not int or value < 0):
            return False
    if statuses.get("battery", OK) != OK and any(row.get(name) is not None for name in
            ("battery_percent", "battery_status", "battery_voltage_uv",
             "battery_voltage_min_design_uv", "battery_current_ua", "battery_power_uw")):
        return False
    events = row.get("power_events", [])
    if (not isinstance(events, list)
            or any(not isinstance(event, str) or event not in POWER_EVENT_LABELS for event in events)
            or len(set(events)) != len(events)):
        return False
    for event, online in (("external-power-connected", True), ("external-power-disconnected", False)):
        if event in events and (statuses.get("external_power", OK) != OK
                                or row.get("external_power_online") is not online):
            return False
    if "battery-voltage-critical" in events and (
            statuses.get("battery", OK) != OK or row.get("battery_status") != "Discharging"
            or not row.get("battery_voltage_uv") or not row.get("battery_voltage_min_design_uv")):
        return False
    return True


def read_timeline(directory: Path | None = None, *, limit: int = 80,
                  boot_id: str | None = None,
                  active_boot_id: str | None = None,
                  tail_bytes: int | None = None) -> dict:
    """Read private samples; the slow observer can bound reads to a file tail."""
    folder = Path(directory) if directory else paths.host_timeline_dir()
    try:
        if boot_id is not None and not _BOOT_ID.fullmatch(boot_id):
            raise ValueError("boot ID inválido")
        if active_boot_id is not None and not _BOOT_ID.fullmatch(active_boot_id):
            raise ValueError("boot ID atual inválido")
        if tail_bytes is not None and not 1024 <= tail_bytes <= _PER_BOOT_LIMIT:
            raise ValueError("janela de leitura inválida")
        if folder.is_symlink() or not folder.is_dir():
            return {"quality": "missing", "reason": "histórico ausente", "samples": [],
                    "capacity": None}
        info = folder.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("diretório de histórico não é privado")
        entries = list(folder.iterdir())
        if len(entries) > 64 or any(p.is_symlink() or not p.is_file() for p in entries):
            raise ValueError("inventário de histórico inválido")
        sizes = {p.name: p.stat().st_size for p in entries}
        total_bytes = sum(sizes.values())
        active_bytes = (sizes.get(f"{active_boot_id}.jsonl")
                        if active_boot_id is not None else None)
        capacity = {"total_bytes": total_bytes, "total_limit_bytes": _TOTAL_LIMIT,
                    "active_boot_bytes": active_bytes,
                    "per_boot_limit_bytes": _PER_BOOT_LIMIT,
                    "at_limit": (total_bytes >= _TOTAL_LIMIT or
                                 active_bytes is not None and active_bytes >= _PER_BOOT_LIMIT),
                    "near_limit": (total_bytes * 100 >= _TOTAL_LIMIT * _CAPACITY_WARNING_PERCENT or
                                   active_bytes is not None and active_bytes * 100 >=
                                   _PER_BOOT_LIMIT * _CAPACITY_WARNING_PERCENT)}
        files = [p for p in entries if p.name.endswith(".jsonl")]
        if boot_id is not None:
            files = [p for p in files if p.name == f"{boot_id}.jsonl"]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        recent = deque(maxlen=max(1, min(limit, 200)))
        malformed = 0
        limited = False
        no_complete_line = False
        for path in reversed(files[:2] if boot_id is None else files):
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_size > _PER_BOOT_LIMIT
                        or info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) != 0o600):
                    raise ValueError("arquivo de histórico fora do limite ou não privado")
                if tail_bytes is None:
                    raw = stream.read(_PER_BOOT_LIMIT + 1)
                else:
                    offset = max(0, info.st_size - tail_bytes)
                    stream.seek(offset)
                    raw = stream.read(tail_bytes)
            if tail_bytes is not None and offset:
                limited = True
                first_end = raw.find(b"\n")
                raw = raw[first_end + 1:] if first_end >= 0 else b""
                if not raw:
                    no_complete_line = True
            for line in raw.splitlines():
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError):
                    malformed += 1
                    continue
                if not _valid_sample(row) or row["boot_id"] != path.stem:
                    malformed += 1
                    continue
                recent.append(row)
        samples = list(recent)
        quality = ("partial" if malformed else "ok" if samples else "unknown"
                   if no_complete_line else "missing")
        reason = (f"{malformed} amostra(s) ilegível(is) preservada(s) na janela" if malformed
                  else "" if samples else "janela sem linha completa"
                  if no_complete_line else "sem amostras locais para o boot"
                  if boot_id is not None else "histórico vazio")
        return {"quality": quality, "reason": reason, "samples": samples,
                "capacity": capacity, "window_limited": limited}
    except (OSError, ValueError, UnicodeError, TypeError) as exc:
        return {"quality": "unknown", "reason": str(exc), "samples": [],
                "capacity": None}


def summarize_boot_timeline(directory: Path, boot_id: str) -> dict:
    """A 64 KiB tail only: evidence near a boot end, never a full-boot claim."""
    report = read_timeline(directory, boot_id=boot_id, limit=80, tail_bytes=65536)
    rows = report["samples"]
    last = rows[-1] if rows else None
    legacy = any(row.get("schema", 1) == 1 for row in rows)
    quality = ("partial" if legacy and report["quality"] == "ok"
               else report["quality"])
    reason = (report["reason"] + "; " if report["reason"] else "")
    if legacy:
        reason += "schema antigo sem qualidade das fontes ou relógio monotônico"
    else:
        reason = report["reason"]
    gaps = []
    for previous, current in zip(rows, rows[1:]):
        a, b = previous.get("mono_ns"), current.get("mono_ns")
        if type(a) is int and type(b) is int and b > a:
            gaps.append(round((b - a) / 1_000_000_000, 2))
    fields = ("at", "mono_ns", "collector_read_ms", "source_issues",
              "mem_available_kb", "swap_used_kb", "psi_mem_avg10", "psi_mem_avg60",
              "psi_io_avg10", "psi_io_avg60", "psi_cpu_avg10", "psi_cpu_avg60",
              "temperature_c", "temperature_sensor",
              "battery_percent", "battery_status", "battery_voltage_uv",
              "battery_voltage_min_design_uv", "battery_current_ua", "battery_power_uw",
              "external_power_online", "power_events", "top_cpu")
    power_event = next((row for row in reversed(rows)
                        if row.get("schema") == 2 and row.get("power_events")), None)
    return {"quality": quality, "reason": reason,
            "last": {key: last.get(key) for key in fields} if last else None,
            "last_power_event": ({key: power_event.get(key) for key in fields}
                                 if power_event else None),
            "recent_samples": len(rows), "recent_max_interval_s": max(gaps, default=None),
            "last_interval_s": gaps[-1] if gaps else None,
            "window_limited": report.get("window_limited", False),
            "scope": "últimas 80 amostras válidas em até 64 KiB; não cobre o boot inteiro"}
