"""Bounded cgroup-v2 readings for the minute audit, not the interactive poller."""
import os
from pathlib import Path

from .. import paths
from ..core.agents import is_helper, provider_of
from ..core.procfs import _parse_stat
from ..core.sessions import read_cgroup


def _member(proc, root):
    name = read_cgroup(proc.pid, root)
    if not name or ".." in Path(name).parts or not name.endswith((".scope", ".service")):
        return None
    try:
        identity = _parse_stat((root / str(proc.pid) / "stat").read_text())
    except OSError:
        return None
    return name if identity and identity[-1] == proc.starttime else None


class WorkloadScopes:
    def __init__(self):
        self.previous = {}

    def sample(self, snapshot):
        root = Path(paths.proc_root())
        cgroups = Path(paths.sys_root()) / "fs/cgroup"
        groups = {}
        seen = set()
        for proc in snapshot.procs:
            provider = provider_of(proc)
            if not provider or provider in seen or is_helper(proc):
                continue
            seen.add(provider)
            group = _member(proc, root)
            if group:
                groups.setdefault(group, []).append(provider)
        # Only the exact Fôlego units in this user's app slice.
        prefix = f"/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/app.slice/"
        for unit in ("app-folego@autostart.service", "folego-accessibility.service"):
            groups.setdefault(prefix + unit, []).append("folego")

        rows, current = [], {}
        for group, labels in groups.items():
            folder = cgroups / group.lstrip("/")
            try:
                inode = folder.stat().st_ino
                memory = int((folder / "memory.current").read_text())
                counters = dict(line.split() for line in (folder / "cpu.stat").read_text().splitlines())
                cpu = int(counters["usage_usec"])
                if inode != folder.stat().st_ino:
                    continue
            except (OSError, ValueError, KeyError):
                continue
            key = snapshot.boot_id, group, inode
            prior = self.previous.get(key)
            rate = None
            if prior and 0 < snapshot.mono - prior[0] <= 150 and cpu >= prior[1]:
                rate = round((cpu - prior[1]) / (snapshot.mono - prior[0]) / 10000, 2)
            current[key] = snapshot.mono, cpu
            rows.append({"unit": folder.name, "observed": labels, "memory_bytes": memory,
                         "cpu_pct": rate})
        self.previous = current
        return rows
