"""Capacity of the local filesystems covering / and HOME."""
from __future__ import annotations

import json
import math
import os
import re
import stat
from hashlib import sha256
from pathlib import Path

from .. import paths
from ..safely.atomicfile import write_atomic
from ..safely.mounts import covering_mount
from .mounts import _unescape

LOCAL_FILESYSTEMS = frozenset({"btrfs", "ext2", "ext3", "ext4", "xfs", "f2fs"})
_SAMPLE_INTERVAL = 3600
_WINDOW = 86400
_MIN_COMPARISON = 900
_MAX_POINTS = 25
_LIMIT_BYTES = 16384
_GIB = 1024 ** 3


def read_mountinfo(proc_root: Path) -> list[dict]:
    with (proc_root / "self/mountinfo").open("rb") as stream:
        raw = stream.read(262145)
    if len(raw) > 262144:
        raise ValueError("mountinfo excede 256 KiB")
    lines = raw.decode().splitlines()
    if len(lines) > 2048:
        raise ValueError("mountinfo excede 2048 linhas")
    mounts = []
    for line in lines:
        fields = line.split()
        sep = fields.index("-", 6)
        if sep + 3 >= len(fields) or not fields[0].isdecimal():
            raise ValueError("registro de montagem inválido")
        mounts.append({"mount": _unescape(fields[4]), "source": _unescape(fields[sep + 2]),
                       "type": fields[sep + 1], "device": fields[2], "mount_id": fields[0]})
    if not mounts:
        raise ValueError("mountinfo sem montagens")
    return mounts


def local_mount(path: Path, mounts: list[dict]) -> dict:
    covering = covering_mount(path, ((row["mount"], row["type"]) for row in mounts))
    matching = [row for row in mounts if covering and row["mount"] == covering[0]]
    if len(matching) != 1:
        raise ValueError("montagem ausente ou ambígua")
    row = matching[0]
    if row["type"] not in LOCAL_FILESYSTEMS or not row["source"].startswith("/dev/"):
        raise ValueError("armazenamento local em bloco não comprovado")
    return row


def _history(path: Path) -> list[dict]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return []
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > _LIMIT_BYTES):
            raise ValueError("histórico de espaço fora do limite ou não privado")
        raw = stream.read(_LIMIT_BYTES + 1)
    data = json.loads(raw)
    if (len(raw) > _LIMIT_BYTES or not isinstance(data, dict)
            or data.get("schema") != 1 or not isinstance(points := data.get("points"), list)
            or len(points) > _MAX_POINTS):
        raise ValueError("histórico de espaço inválido")
    previous = -1
    for point in points:
        at = point.get("at") if isinstance(point, dict) else None
        if (type(at) not in (int, float) or not math.isfinite(at) or at <= previous
                or not isinstance(values := point.get("free"), dict) or len(values) not in (1, 2)
                or any(not re.fullmatch(r"[0-9a-f]{64}", key) or type(value) is not int or value < 0
                       for key, value in values.items())):
            raise ValueError("amostra de espaço inválida")
        previous = at
    return points


def observe_storage(mounts, *, sys_root, state_path, now, record=False, home=None,
                    statvfs=os.statvfs):
    home = Path.home() if home is None else Path(home)
    volumes = []
    groups = {}
    problems = []
    measurements = {}
    for label, path in (("Pasta pessoal", home), ("Sistema", Path("/"))):
        try:
            path = path.resolve(strict=True)
            mount = local_mount(path, mounts)
            # Btrfs exposes separate mount IDs and statvfs fsids for subvolumes
            # sharing the same pool. Match the mounted filesystem and source.
            vfs = statvfs(mount["mount"])
            block = vfs.f_frsize or vfs.f_bsize
            if block <= 0 or not 0 <= vfs.f_bavail <= vfs.f_bfree <= vfs.f_blocks or not vfs.f_blocks:
                raise ValueError("contadores de blocos incoerentes")
            total = vfs.f_blocks * block
            available = vfs.f_bavail * block
            used = (vfs.f_blocks - vfs.f_bfree) * block
            group = (mount["type"], mount["source"], mount["device"], total)
            if group in groups:
                groups[group]["roles"].append(label)
                continue
            ratio = used / (used + available) if used + available else 1
            level = ("critical" if available < 10 * _GIB or ratio >= .95 else
                     "high" if available < 20 * _GIB or ratio >= .90 else "ok")
            device = mount["source"].removeprefix("/dev/")
            nvme = (re.fullmatch(r"nvme[0-9]+n[0-9]+(?:p[0-9]+)?", device) is not None
                    and (sys_root / "class/block" / device).exists())
            fsid = getattr(vfs, "f_fsid", 0)
            row = {"roles": [label], "mount": mount["mount"], "source": mount["source"],
                   "type": mount["type"], "nvme": nvme, "total_bytes": total,
                   "available_bytes": available, "used_pct": round(ratio * 100, 1),
                   "level": level, "trend": None, "trend_available": bool(fsid)}
            groups[group] = row
            volumes.append(row)
            if fsid:
                key = sha256(repr((mount["type"], mount["source"], fsid, total)).encode()).hexdigest()
                measurements[key] = row
        except (OSError, ValueError) as exc:
            problems.append(f"{label}: {exc}")

    history_reason = ""
    try:
        points = _history(state_path)
        if points and points[-1]["at"] > now:
            raise ValueError("relógio anterior à última amostra de espaço")
        recent = [point for point in points if now - point["at"] <= _WINDOW]
        for key, row in measurements.items():
            baseline = next((p for p in recent if key in p["free"]
                             and now - p["at"] >= _MIN_COMPARISON), None)
            if baseline is not None:
                row["trend"] = {"elapsed_s": round(now - baseline["at"]),
                                "available_delta_bytes": row["available_bytes"] - baseline["free"][key]}
        if (record and measurements and not problems
                and (not recent or now - recent[-1]["at"] >= _SAMPLE_INTERVAL)):
            point = {"at": now, "free": {key: row["available_bytes"]
                                         for key, row in measurements.items()}}
            state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_atomic(state_path, json.dumps({"schema": 1, "points": [*recent, point][-_MAX_POINTS:]})
                         .encode(), mode=0o600)
    except (OSError, ValueError, OverflowError) as exc:
        history_reason = str(exc)
    return {"quality": ("partial" if volumes and problems else "unknown" if problems else "ok"),
            "reason": " · ".join(problems), "history_reason": history_reason, "volumes": volumes}
