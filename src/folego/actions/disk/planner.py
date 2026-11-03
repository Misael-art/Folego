"""Disk hygiene M5 — declarative targets and the dry-run plan.

Nothing here mutates the filesystem. A target that would fall outside the
user's own directories (or on a hazardous mount such as /mnt/sdcard) is
refused *before* it is read, so a bad allow-list entry cannot hang a walk.
"""
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from ... import paths
from ...safely import guard
from .measure import measure_tree

DAY_S = 86_400


@dataclass(frozen=True)
class DiskTarget:
    id: str
    label: str
    path: str  # template expanded with {home} {cache} {data} {state}
    mode: str = "children"  # "children" = one item per child dir; "self" = whole tree
    stale_days: float | None = 30.0

    def expand(self, home: Path) -> str:
        home = Path(home)
        return self.path.format(
            home=home,
            cache=home / ".cache",
            data=paths.data_dir(),
            config=paths.config_dir().parent,
            state=paths.state_dir(),
        )


@dataclass(frozen=True)
class PlanItem:
    target_id: str
    label: str
    path: str
    bytes: int
    files: int
    newest_ns: int
    age_days: float
    reclaimable: bool
    ok: bool
    reason: str
    errors: tuple
    truncated: bool

    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "label": self.label,
            "path": self.path,
            "bytes": self.bytes,
            "files": self.files,
            "age_days": round(self.age_days, 1),
            "reclaimable": self.reclaimable,
            "reason": self.reason,
            "errors": list(self.errors),
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class DiskPlan:
    items: tuple
    total_bytes: int
    scanned_bytes: int
    digest: str
    generated_at: float

    def to_dict(self) -> dict:
        return {
            "digest": self.digest,
            "generated_at": self.generated_at,
            "total_bytes": self.total_bytes,
            "scanned_bytes": self.scanned_bytes,
            "items": [i.to_dict() for i in self.items],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def reclaimable(self) -> tuple:
        return tuple(i for i in self.items if i.reclaimable and i.bytes > 0)


def default_targets() -> tuple:
    """Allow-listed read-only hygiene probes. Every path is under {home}; anything
    else is refused by the guard, so this list is also the blast radius."""
    return (
        DiskTarget("pip", "Cache do pip", "{home}/.cache/pip", mode="self", stale_days=None),
        DiskTarget("npm", "Cache do npm", "{home}/.npm/_cacache", mode="self", stale_days=None),
        DiskTarget("thumbnails", "Miniaturas", "{home}/.cache/thumbnails", mode="self",
                   stale_days=None),
        DiskTarget("uv", "Cache do uv", "{home}/.cache/uv", mode="self", stale_days=None),
        DiskTarget("browser-cache", "Cache de navegadores",
                   "{home}/.cache/microsoft-edge", mode="self", stale_days=None),
        DiskTarget("stale-caches", "Caches antigos do usuário", "{home}/.cache",
                   mode="children", stale_days=30.0),
        DiskTarget("trash", "Lixeira", "{home}/.local/share/trash", mode="self",
                   stale_days=None),
    )


def _under(path_str: str, root) -> bool:
    root_str = str(root)
    return path_str == root_str or path_str.startswith(root_str + os.sep)


def default_allowed_roots(home=None) -> list:
    home = Path(home) if home else Path.home()
    return [home, paths.data_dir(), paths.config_dir().parent, paths.state_dir()]


def _check(candidate: Path, allowed_roots, resolve_fn):
    verdict = guard.validate_target(candidate, allowed_roots)
    if not verdict.ok:
        return verdict
    resolved = str(resolve_fn(candidate))
    if not any(_under(resolved, Path(r).resolve()) for r in allowed_roots):
        return guard.GuardVerdict(False, "refused: resolves outside allowed roots")
    return verdict


def build_plan(targets, *, home=None, now: float | None = None,
               measure=measure_tree, allowed_roots=None, deadline_s: float | None = 30.0,
               resolve_fn=lambda p: Path(p).resolve()) -> DiskPlan:
    home = Path(home) if home else Path.home()
    now = time.time() if now is None else now
    roots = list(allowed_roots) if allowed_roots else default_allowed_roots(home)

    items: list[PlanItem] = []
    seen: set[str] = set()
    for target in targets:
        base = Path(os.path.expanduser(target.expand(home)))
        verdict = _check(base, roots, resolve_fn)
        if not verdict.ok:
            items.append(PlanItem(target.id, target.label, str(base), 0, 0, 0, 0.0,
                                  False, False, verdict.reason, (), False))
            continue
        if not base.is_dir():
            continue
        try:
            if target.mode == "children":
                candidates = sorted((c for c in base.iterdir() if c.is_dir()),
                                    key=lambda p: p.name)
            else:
                candidates = [base]
        except OSError as err:
            items.append(PlanItem(target.id, target.label, str(base), 0, 0, 0, 0.0,
                                  False, False, f"refused: cannot list directory ({err.strerror})",
                                  (), False))
            continue
        for child in candidates:
            if str(child) in seen:
                continue
            child_verdict = _check(child, roots, resolve_fn)
            if not child_verdict.ok:
                items.append(PlanItem(target.id, target.label, str(child), 0, 0, 0, 0.0,
                                      False, False, child_verdict.reason, (), False))
                continue
            stat = measure(child, deadline_s=deadline_s)
            seen.add(str(stat.path))
            age_days = max(0.0, (now - stat.newest_ns / 10**9) / DAY_S)
            # leitura incompleta não é promessa: um walk com erro ou truncado sabe o
            # tamanho "por baixo" e nunca entra no total elegível (R03)
            reclaimable = (stat.bytes > 0 and not stat.errors and not stat.truncated and
                           (target.stale_days is None or age_days >= target.stale_days))
            items.append(PlanItem(
                target.id, target.label, str(stat.path), stat.bytes, stat.files,
                stat.newest_ns, age_days, reclaimable, True, "ok",
                stat.errors, stat.truncated))

    refused = [i for i in items if not i.ok]
    measured = sorted((i for i in items if i.ok),
                      key=lambda i: (-i.bytes, i.path))
    ordered = tuple(measured) + tuple(sorted(refused, key=lambda i: i.path))
    total = sum(i.bytes for i in ordered if i.reclaimable)
    scanned = sum(i.bytes for i in ordered if i.ok)
    digest_src = json.dumps([[i.path, i.bytes] for i in ordered], ensure_ascii=False)
    return DiskPlan(ordered, total, scanned,
                    hashlib.sha256(digest_src.encode()).hexdigest(), now)


@dataclass(frozen=True)
class VolumeStat:
    mount: str
    total_bytes: int
    free_bytes: int
    used_frac: float

    @property
    def critical(self) -> bool:
        return self.total_bytes > 0 and self.free_bytes / self.total_bytes < 0.05

    @property
    def free_frac(self) -> float:
        return self.free_bytes / self.total_bytes if self.total_bytes else 0.0

    def to_dict(self) -> dict:
        return {"mount": self.mount, "total_bytes": self.total_bytes,
                "free_bytes": self.free_bytes, "used_pct": round(self.used_frac * 100, 1),
                "critical": self.critical}


def volume_report(mounts=("/", "/tmp", "/home"), *, home=None) -> tuple:
    """Space as the kernel sees it. A full /tmp tmpfs raises ENOSPC even when the
    data partition has gigabytes free, so hygiene must look at both."""
    seen = []
    for mount in mounts:
        target = Path(str(mount).format(home=home or Path.home()))
        if not target.is_dir():
            continue
        try:
            vfs = os.statvfs(target)
        except OSError:
            continue
        total = vfs.f_blocks * vfs.f_frsize
        free = vfs.f_bavail * vfs.f_frsize
        used = (vfs.f_blocks - vfs.f_bfree) * vfs.f_frsize
        used_frac = used / total if total else 0.0
        seen.append(VolumeStat(str(target), total, free, used_frac))
    return tuple(seen)


def format_volumes(volumes) -> str:
    lines = []
    for vol in volumes:
        flag = " 🔴 espaço crítico" if vol.critical else ""
        lines.append(
            f"{vol.mount} · livre {fmt_bytes(vol.free_bytes)} de "
            f"{fmt_bytes(vol.total_bytes)} ({vol.used_frac * 100:.0f}% usado) · "
            f"{vol.free_frac * 100:.0f}% livre{flag}")
    return "\n".join(lines)


def fmt_bytes(num: int) -> str:
    def dec(value: float) -> str:
        return f"{value:.1f}".replace(".", ",")

    gib = num / 1024**3
    if gib >= 1:
        return dec(gib) + " GB"
    mib = num / 1024**2
    if mib >= 1:
        return dec(mib) + " MB"
    return dec(num / 1024) + " KB"


def format_report(plan: DiskPlan) -> str:
    lines = []
    for item in plan.items:
        if not item.ok:
            lines.append(f"⛔ {item.label} · {item.path} · {item.reason}")
            continue
        mark = "♻" if item.reclaimable else "·"
        extra = " (leitura truncada)" if item.truncated else ""
        lines.append(
            f"{mark} {item.label} · {os.path.basename(item.path) or item.path} · "
            f"{fmt_bytes(item.bytes)} · {item.age_days:.0f} d{extra}")
    lines.append("")
    lines.append(f"total recuperável: {fmt_bytes(plan.total_bytes)} · "
                 f"analisado: {fmt_bytes(plan.scanned_bytes)} · "
                 f"impressão: {plan.digest[:12]}")
    return "\n".join(lines)
