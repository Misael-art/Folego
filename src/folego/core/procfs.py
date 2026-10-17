"""Read-only /proc parsers. Every reader degrades to None on a missing or
malformed file — one absent knob never voids a snapshot."""
from pathlib import Path

from .. import paths
from .snapshot import LoadAvg, MemInfo, Pressure, ProcInfo, SwapInfo


def _read(root: Path, name: str) -> str | None:
    try:
        return (root / name).read_text()
    except OSError:
        return None


def read_meminfo(root: Path | None = None) -> MemInfo | None:
    raw = _read(root or Path(paths.proc_root()), "meminfo")
    if raw is None:
        return None
    fields = {}
    for line in raw.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[-1] == "kB":
            fields[key.strip()] = int(parts[0])
    if "MemTotal" not in fields or "MemAvailable" not in fields:
        return None
    return MemInfo(fields["MemTotal"], fields["MemAvailable"])


def read_pressure(root: Path | None = None, source: str = "memory") -> Pressure | None:
    raw = _read(root or Path(paths.proc_root()), f"pressure/{source}")
    if raw is None:
        return None
    for line in raw.splitlines():
        parts = line.split()
        if parts and parts[0] == "some":
            kv = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
            try:
                return Pressure(float(kv["avg10"]), float(kv["avg60"]),
                                float(kv["avg300"]), int(kv["total"]))
            except (KeyError, ValueError):
                return None
    return None


def read_loadavg(root: Path | None = None) -> LoadAvg | None:
    raw = _read(root or Path(paths.proc_root()), "loadavg")
    if raw is None:
        return None
    p = raw.split()
    try:
        run, total = p[3].split("/")
        return LoadAvg(float(p[0]), float(p[1]), float(p[2]), int(run), int(total))
    except (IndexError, ValueError):
        return None


def read_swaps(root: Path | None = None) -> list[SwapInfo]:
    raw = _read(root or Path(paths.proc_root()), "swaps")
    if raw is None:
        return []
    out = []
    for line in raw.splitlines()[1:]:
        p = line.split()
        if len(p) >= 5:
            try:
                out.append(SwapInfo(p[0], p[1], int(p[2]), int(p[3]), int(p[4])))
            except ValueError:
                continue
    return out


def _parse_stat(content: str) -> tuple | None:
    # comm can contain spaces/parens: anchor on first '(' and last ')'
    try:
        head, rest = content.split("(", 1)
        _comm, rest = rest.rsplit(")", 1)
        f = rest.split()
        return (int(head), f[0], int(f[1]), int(f[2]), int(f[3]),
                int(f[10]), int(f[11]), int(f[16]))
    except (ValueError, IndexError):
        return None


def read_proc(root: Path, pid: int) -> ProcInfo | None:
    try:
        stat_raw = (root / str(pid) / "stat").read_text()
        status_raw = (root / str(pid) / "status").read_text()
        cmdline_raw = (root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return None
    parsed = _parse_stat(stat_raw)
    if parsed is None:
        return None
    pid_, state, ppid, pgrp, session, utime, stime, starttime = parsed
    rss_kb = swap_kb = uid = 0
    for line in status_raw.splitlines():
        if line.startswith("VmRSS:"):
            rss_kb = int(line.split()[1])
        elif line.startswith("VmSwap:"):
            swap_kb = int(line.split()[1])
        elif line.startswith("Uid:"):
            uid = int(line.split()[1])
    comm_path = root / str(pid) / "comm"
    comm = comm_path.read_text().strip() if comm_path.exists() else ""
    cmdline = tuple(c.decode("utf-8", "replace") for c in cmdline_raw.split(b"\0") if c)
    if not comm and cmdline:
        comm = cmdline[0].rsplit("/", 1)[-1]
    return ProcInfo(pid_, comm, state, ppid, pgrp, session, utime, stime, starttime,
                    rss_kb, swap_kb, uid, cmdline)


def list_processes(root: Path | None = None) -> list[ProcInfo]:
    root = root or Path(paths.proc_root())
    out = []
    try:
        names = [n for n in root.iterdir() if n.name.isdigit()]
    except OSError:
        return []
    for n in names:
        info = read_proc(root, int(n.name))
        if info is not None:
            out.append(info)
    return out
