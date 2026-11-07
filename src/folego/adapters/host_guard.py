"""Bounded observation of host integrity. Never opens a mounted device path."""
from __future__ import annotations

import json
import itertools
import os
import re
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

from .. import paths
from .host_timeline import read_timeline, summarize_boot_timeline
from ..safely.atomicfile import write_atomic

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_COUNTERS = {"write_errs", "read_errs", "flush_errs", "corruption_errs", "generation_errs"}
_NTFS_PATTERN = ("ntfs_mst_post_read_fixup_warn|[Nn][Tt][Ff][Ss].*(corrupt|[Ee]rror)"
                 "|Corrupt index block signature")
_NTFS_INDEX = re.compile(r"^Corrupt index block signature: vcn ([0-9]{1,20}) inode ([0-9]{1,20})$")


def _command(argv: list[str], timeout: float = 3.0) -> tuple[int, str, str]:
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, "", str(exc)
    return result.returncode, result.stdout[:131072], result.stderr[:4096]


def _read_small(path: Path, limit: int = 4096) -> str:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"fonte excede {limit} bytes")
    return raw.decode("utf-8")


def _stats(raw: str) -> dict[str, int]:
    found = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[0] not in _COUNTERS or parts[0] in found:
            raise ValueError("contador Btrfs malformado")
        value = int(parts[1])
        if value < 0:
            raise ValueError("contador Btrfs negativo")
        found[parts[0]] = value
    if set(found) != _COUNTERS:
        raise ValueError("contadores Btrfs incompletos")
    return found


def _mounts(proc_root: Path) -> tuple[list[dict], str]:
    try:
        raw = _read_small(proc_root / "self/mountinfo", 262144)
    except (OSError, ValueError, UnicodeError) as exc:
        return [], f"mountinfo indisponível: {exc}"
    lines = raw.splitlines()
    if len(lines) > 2048:
        return [], "inventário de volumes excede 2048 linhas; coleta recusada"
    found = []
    for line in lines:
        fields = line.split()
        if "-" not in fields:
            continue
        sep = fields.index("-")
        if sep + 2 >= len(fields) or len(fields) < 5:
            continue
        kind, source = fields[sep + 1:sep + 3]
        mount = fields[4].replace("\\040", " ")
        if kind in ("btrfs", "ntfs", "ntfs3", "fuseblk"):
            found.append({"mount": mount, "source": source, "type": kind})
    if len(found) > 128:
        return found[:128], "inventário de volumes parcial (limite 128)"
    return found, ""


def _btrfs(sys_root: Path) -> tuple[list[dict], str]:
    root = sys_root / "fs/btrfs"
    try:
        entries = list(itertools.islice(root.iterdir(), 33))
    except OSError as exc:
        return [], f"sysfs Btrfs indisponível: {exc}"
    if len(entries) > 32:
        return [], "inventário Btrfs excede 32 entradas; coleta recusada"
    filesystems = [p for p in entries if _UUID.fullmatch(p.name)]
    if len(filesystems) > 16:
        return [], "mais de 16 filesystems Btrfs; coleta recusada"
    out = []
    for fs in filesystems:
        try:
            entries = list(itertools.islice((fs / "devinfo").iterdir(), 33))
        except OSError as exc:
            out.append({"id": fs.name, "quality": "unknown", "reason": str(exc)})
            continue
        if len(entries) > 32:
            out.append({"id": fs.name, "quality": "unknown", "reason": "mais de 32 dispositivos"})
            continue
        devices = [p for p in entries if p.name.isdecimal()]
        if len(devices) > 32:
            out.append({"id": fs.name, "quality": "unknown", "reason": "mais de 32 dispositivos"})
            continue
        for device in devices:
            key = f"{fs.name}:{device.name}"
            try:
                counters = _stats(_read_small(device / "error_stats", 512))
                out.append({"id": key, "quality": "ok", "counters": counters})
            except (OSError, ValueError, UnicodeError) as exc:
                out.append({"id": key, "quality": "unknown", "reason": str(exc)})
    return out, ""


def _load_baseline(path: Path) -> tuple[dict | None, str]:
    try:
        if path.is_symlink():
            return None, "baseline é link simbólico"
        raw = _read_small(path, 16384)
    except FileNotFoundError:
        return {"schema": 1, "devices": {}}, "novo"
    except (OSError, ValueError, UnicodeError) as exc:
        return None, f"baseline ilegível: {exc}"
    try:
        data = json.loads(raw)
        devices = data["devices"]
        if data.get("schema") != 1 or not isinstance(devices, dict) or len(devices) > 64:
            raise ValueError("schema ou inventário inválido")
        for key, entry in devices.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                raise ValueError("dispositivo inválido")
            counters = entry["counters"]
            if set(counters) != _COUNTERS or any(type(v) is not int or v < 0 for v in counters.values()):
                raise ValueError("contadores inválidos")
    except (ValueError, TypeError, KeyError) as exc:
        return None, f"baseline inválido: {exc}"
    return data, ""


def _compare_and_record(rows: list[dict], path: Path, record: bool, now: float,
                        boot_id: str) -> tuple[list[dict], str]:
    baseline, problem = _load_baseline(path)
    updated = dict(baseline["devices"]) if baseline is not None else {}
    changed = False
    for row in rows:
        if row["quality"] != "ok":
            continue
        current = row["counters"]
        previous = updated.get(row["id"])
        row["delta"] = None
        row["trend"] = "unknown"
        if previous is not None:
            old = previous["counters"]
            if all(current[k] >= old[k] for k in _COUNTERS):
                row["delta"] = {k: current[k] - old[k] for k in _COUNTERS}
                row["trend"] = "increased" if any(row["delta"].values()) else "stable"
            else:
                row["reason"] = "contador diminuiu; reset ou identidade alterada, tendência desconhecida"
        if baseline is not None and record and boot_id:
            last_event = previous.get("last_event") if previous else None
            if row["trend"] == "increased":
                last_event = {"at": now, "delta": row["delta"]}
            entry = {"counters": current, "boot_id": boot_id}
            if last_event and isinstance(last_event, dict):
                entry["last_event"] = last_event
            if previous != entry:
                updated[row["id"]] = entry
                changed = True
        event = updated.get(row["id"], {}).get("last_event")
        row["recent_delta"] = (event.get("delta") if isinstance(event, dict)
                               and isinstance(event.get("at"), (int, float))
                               and 0 <= now - event["at"] <= 86400 else None)
    if record and changed and baseline is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_atomic(path, json.dumps({"schema": 1, "devices": updated},
                                          sort_keys=True).encode(), mode=0o600)
        except OSError as exc:
            problem = f"baseline não salvo: {exc}"
    return rows, problem


def _ntfs_events(run, mounts: list[dict]) -> dict:
    argv = ["journalctl", "-b", "--since=-10min", "-n", "80", "-g", _NTFS_PATTERN,
            "-o", "json", "--no-pager"]
    code, out, err = run(argv, 3.0)
    if code not in (0, 1) or (code == 1 and "No entries" not in err and err.strip()):
        return {"quality": "unknown", "reason": err or "journal indisponível",
                "count_10m": None, "mount": None}
    entries = []
    affected = set()
    for line in out.splitlines()[:80]:
        try:
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise ValueError("evento do journal não é objeto")
        except (ValueError, TypeError):
            return {"quality": "unknown", "reason": "evento do journal malformado",
                    "count_10m": None, "mount": None}
        entries.append(entry)
        message = entry.get("MESSAGE")
        match = _NTFS_INDEX.fullmatch(message) if isinstance(message, str) else None
        if match:
            affected.add((int(match[2]), int(match[1])))
    # Atribuição só é confiável quando há exatamente um volume NTFS/fuseblk.
    volumes = [m for m in mounts if m["type"] in ("ntfs", "ntfs3", "fuseblk")]
    mount = volumes[0] if len(volumes) == 1 else None
    try:
        timestamps = []
        for entry in entries:
            raw_time = entry.get("__REALTIME_TIMESTAMP")
            if not isinstance(raw_time, str) or not raw_time.isdecimal() or len(raw_time) > 17:
                raise ValueError("horário do journal inválido")
            timestamps.append(int(raw_time))
        last_us = max(timestamps, default=0)
        last_at = (datetime.fromtimestamp(last_us / 1_000_000).astimezone()
                   .isoformat(timespec="seconds") if last_us else None)
    except (ValueError, OverflowError, OSError) as exc:
        return {"quality": "unknown", "reason": str(exc), "count_10m": None,
                "mount": None}
    return {"quality": "partial" if len(entries) == 80 else "ok",
            "count_10m": len(entries),
            "index_blocks_10m": len(affected),
            "index_inodes_10m": len({inode for inode, _ in affected}),
            "mount": mount, "attribution": "single_candidate" if mount else "unknown",
            "last_at": last_at, "window_minutes": 10}


_WATCHED_SERVICES = (
    ("folego-accessibility.service", "Fôlego"),
    ("folego-performance.service", "Fôlego"),
    ("phasezero-input-restore.service", "PhaseZero"),
    ("phasezero-ai-memory-watch.service", "PhaseZero"),
    ("codex-quota-panel.service", "SteamZero (legado)"),
)


def _services(run, watched=_WATCHED_SERVICES) -> dict:
    # One bounded query for named owners. An inactive, disabled unit is an
    # observation, not an incident or permission to start it.
    watched = tuple(watched)
    if (not watched or len(watched) > 8 or
            any(not isinstance(row, (tuple, list)) or len(row) != 2 or
                not isinstance(row[0], str) or
                not re.fullmatch(r"[a-z0-9@_.-]+\.service", row[0]) or
                not isinstance(row[1], str) or not 0 < len(row[1]) <= 80
                for row in watched)):
        return {"quality": "unknown", "reason": "inventário de serviços inválido", "items": [], "inventory": []}
    code, raw, watch_error = run(
        ["systemctl", "--user", "show", *(name for name, _ in watched),
         "-p", "Id", "-p", "LoadState", "-p", "UnitFileState",
         "-p", "ActiveState", "-p", "SubState", "-p", "Result", "-p", "NRestarts"], 2.0)
    inventory = []
    owners = dict(watched)
    if code == 0 and len(raw) <= 16384:
        seen = set()
        for block in raw.split("\n\n")[:len(watched) + 1]:
            props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            name = props.get("Id", "")
            if name not in owners or name in seen:
                continue
            seen.add(name)
            try:
                restarts = int(props.get("NRestarts", ""))
                if restarts < 0: raise ValueError
            except ValueError:
                restarts = None
            quality = ("ok" if props.get("LoadState") == "loaded" and
                       props.get("ActiveState") in ("active", "inactive", "failed", "activating")
                       and restarts is not None else "unknown")
            inventory.append({"unit": name, "owner": owners[name], "source": "systemctl --user show",
                              "quality": quality, "load": props.get("LoadState", "unknown"),
                              "enabled": props.get("UnitFileState", "unknown"),
                              "state": props.get("ActiveState", "unknown"),
                              "substate": props.get("SubState", "unknown"),
                              "result": props.get("Result", "unknown"),
                              "restarts": restarts})
        for name, owner in watched:
            if name not in seen:
                inventory.append({"unit": name, "owner": owner, "source": "systemctl --user show",
                                  "quality": "unknown", "reason": "unit ausente na consulta"})
    else:
        inventory = [{"unit": name, "owner": owner, "source": "systemctl --user show",
                      "quality": "unknown", "reason": watch_error or "consulta indisponível ou excessiva"}
                     for name, owner in watched]
    code, out, err = run(["systemctl", "--user", "list-units", "--type=service",
                          "--state=activating,failed", "--plain", "--no-legend", "--no-pager"], 3.0)
    if code != 0:
        return {"quality": "unknown", "reason": err or "systemd do usuário indisponível", "items": [],
                "inventory": inventory}
    names = []
    for line in out.splitlines():
        parts = line.lstrip("● ").split()
        if parts and parts[0].endswith(".service"):
            names.append(parts[0])
    if len(names) > 16:
        return {"quality": "partial", "reason": "mais de 16 units candidatas", "items": [],
                "inventory": inventory}
    items = []
    for name in names:
        code, raw, err = run(["systemctl", "--user", "show", name, "-p", "NRestarts",
                               "-p", "ActiveState", "-p", "SubState", "-p", "Result"], 2.0)
        if code != 0:
            items.append({"unit": name, "quality": "unknown", "reason": err})
            continue
        props = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
        try:
            restarts = int(props.get("NRestarts", ""))
            if restarts < 0:
                raise ValueError
        except ValueError:
            items.append({"unit": name, "quality": "unknown", "reason": "NRestarts inválido"})
            continue
        if restarts >= 5 or props.get("ActiveState") == "failed":
            items.append({"unit": name, "owner": owners.get(name, "desconhecido"),
                          "source": "systemctl --user show", "quality": "ok", "restarts": restarts,
                          "state": props.get("SubState", ""), "result": props.get("Result", "")})
    missing = sum(item["quality"] != "ok" for item in inventory)
    return {"quality": "partial" if missing else "ok",
            "reason": f"{missing} unit(s) sem leitura confiável" if missing else "",
            "items": sorted(items, key=lambda x: -x.get("restarts", 0)),
            "inventory": inventory}


def _boots(run) -> dict:
    code, out, err = run(["journalctl", "--list-boots", "-n", "4", "--no-pager"], 3.0)
    if code != 0:
        return {"quality": "unknown", "reason": err or "histórico indisponível", "items": []}
    items = []
    for line in out.splitlines()[:8]:
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and re.fullmatch(r"[0-9a-f]{32}", parts[1]):
            items.append({"boot_id": parts[1], "period": parts[2]})
            if len(items) == 4:
                break
    if len(items) < 2:
        return {"quality": "partial", "reason": "boot anterior ausente no journal", "items": items}
    incomplete = False
    for item in items[:-1]:
        code, events, err = run(["journalctl", "-b", item["boot_id"],
                                 "-u", "systemd-logind.service",
                                 "-g", "System is powering down\\.", "-n", "1",
                                 "-o", "cat", "--no-pager"], 2.0)
        if code not in (0, 1) or (code == 1 and err.strip()):
            item["end"] = "unknown"
            item["reason"] = err or "fim do boot ilegível"
            incomplete = True
            continue
        item["end"] = ("shutdown_recorded" if code == 0 and
                       "System is powering down." in events else "inconclusive")
    previous = items[-2]
    without_record = sum(item.get("end") == "inconclusive" for item in items[:-1])
    reason = (f"{without_record} "
              f"{'boot anterior' if without_record == 1 else 'boots anteriores'} "
              "sem registro de desligamento do logind no diário; causa desconhecida"
              if without_record else "desligamento registrado nos boots anteriores consultáveis")
    if incomplete:
        reason += "; parte do histórico indisponível"
    return {"quality": "partial" if incomplete else "ok", "items": items,
            "previous_end": previous.get("end", "unknown"), "reason": reason}


def _last_journal_entry(run, boot_id: str) -> dict:
    """Last retained event only; a silent tail of a failed boot remains unknown."""
    code, out, err = run(["journalctl", "-b", boot_id, "-n", "1", "-o", "json",
                          "--no-pager"], 2.0)
    if code != 0:
        return {"quality": "unknown", "reason": err or "fim do journal indisponível",
                "last_at": None, "mono_us": None}
    try:
        row = json.loads(out.strip())
        stamp = row["__REALTIME_TIMESTAMP"]
        if (not isinstance(row, dict) or not isinstance(stamp, str)
                or not stamp.isdecimal() or len(stamp) > 17):
            raise ValueError("horário do último evento inválido")
        last_at = datetime.fromtimestamp(int(stamp) / 1_000_000).astimezone()
        mono = row.get("__MONOTONIC_TIMESTAMP")
        mono_us = int(mono) if (isinstance(mono, str) and mono.isdecimal()
                                and len(mono) <= 17) else None
    except (ValueError, KeyError, TypeError, OverflowError, OSError) as exc:
        return {"quality": "unknown", "reason": str(exc), "last_at": None,
                "mono_us": None}
    return {"quality": "ok", "reason": "último registro retido, não o fim comprovado do boot",
            "last_at": last_at.isoformat(timespec="seconds"), "mono_us": mono_us}


class HostObserver:
    """Slow probe. `record` only commits a tiny Btrfs baseline for the GUI."""

    def __init__(self, *, proc_root: Path | None = None, sys_root: Path | None = None,
                 state_path: Path | None = None, run=None, record: bool = False,
                 clock=None, timeline_dir: Path | None = None, service_watch=None):
        self.proc_root = Path(proc_root) if proc_root else Path(paths.proc_root())
        self.sys_root = Path(sys_root) if sys_root else Path(paths.sys_root())
        self.state_path = Path(state_path) if state_path else paths.host_guard_path()
        self.run = run or _command
        self.record = record
        self.clock = clock or time.time
        self.timeline_dir = timeline_dir if timeline_dir is not None else paths.host_timeline_dir()
        self.service_watch = _WATCHED_SERVICES if service_watch is None else tuple(service_watch)
        self._boot_cache = None

    def observe(self) -> dict:
        now = self.clock()
        started = time.monotonic()
        deadline = started + 8.0

        def run(argv, timeout):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return -1, "", "orçamento de 8 s esgotado"
            return self.run(argv, min(timeout, remaining))

        try:
            boot_id = _read_small(self.proc_root / "sys/kernel/random/boot_id", 64).strip()
        except (OSError, ValueError, UnicodeError):
            boot_id = ""
        mounts, mounts_problem = _mounts(self.proc_root)
        btrfs, btrfs_problem = _btrfs(self.sys_root)
        btrfs, baseline_problem = _compare_and_record(btrfs, self.state_path,
                                                        self.record, now, boot_id)
        ntfs = _ntfs_events(run, mounts if not mounts_problem else [])
        services = _services(run, self.service_watch)
        timeline = read_timeline(self.timeline_dir, limit=1, boot_id=boot_id or None,
                                 tail_bytes=65536,
                                 active_boot_id=boot_id or None)
        last_sample = timeline["samples"][-1] if timeline["samples"] else None
        if last_sample and last_sample.get("boot_id") == boot_id:
            try:
                age = now - datetime.fromisoformat(last_sample["at"]).timestamp()
                if age > 120 or age < -30:
                    timeline = {"quality": "stale", "reason": "última amostra antiga",
                                "samples": timeline["samples"],
                                "capacity": timeline["capacity"]}
            except (ValueError, TypeError):
                timeline = {"quality": "unknown", "reason": "horário inválido",
                            "samples": timeline["samples"],
                            "capacity": timeline["capacity"]}
        if self._boot_cache is None or self._boot_cache[0] != boot_id:
            boots = _boots(run)
            for item in boots["items"][:-1]:
                timeline_id = str(uuid.UUID(hex=item["boot_id"]))
                item["timeline"] = summarize_boot_timeline(self.timeline_dir, timeline_id)
                item["journal_tail"] = _last_journal_entry(run, item["boot_id"])
                boot_last = item["timeline"].get("last")
                last_event = item["journal_tail"].get("last_at")
                item["sample_to_journal_s"] = None
                item["gap_clock"] = None
                if boot_last and last_event:
                    sample_mono = boot_last.get("mono_ns")
                    event_mono = item["journal_tail"].get("mono_us")
                    if type(sample_mono) is int and type(event_mono) is int:
                        difference = event_mono / 1_000_000 - sample_mono / 1_000_000_000
                        item["gap_clock"] = "monotonic"
                    else:
                        difference = (datetime.fromisoformat(last_event).timestamp()
                                      - datetime.fromisoformat(boot_last["at"]).timestamp())
                        item["gap_clock"] = "wall"
                    if difference >= 0:
                        item["sample_to_journal_s"] = round(difference, 1)
                    else:
                        item["gap_clock"] = None
            self._boot_cache = (boot_id, boots)
        return {"observed_at": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"),
                "boot_id": boot_id, "mounts_quality": "unknown" if mounts_problem else "ok",
                "mounts_reason": mounts_problem, "btrfs": btrfs,
                "btrfs_quality": "unknown" if btrfs_problem else "ok",
                "btrfs_reason": btrfs_problem,
                "baseline_quality": "unknown" if baseline_problem and baseline_problem != "novo" else "ok",
                "baseline_reason": baseline_problem,
                "ntfs": ntfs, "services": services, "boots": self._boot_cache[1],
                "observer_duration_ms": round((time.monotonic() - started) * 1000, 2),
                "timeline": {"quality": timeline["quality"], "reason": timeline["reason"],
                             "capacity": timeline["capacity"],
                             "window_limited": timeline.get("window_limited", False),
                             "last_at": last_sample["at"] if last_sample else None,
                             "last_boot_id": last_sample["boot_id"] if last_sample else None}}
