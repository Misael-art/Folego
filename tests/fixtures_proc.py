"""Builder for fake /proc trees used by collector tests.

stat field layout after ')' (0-based): state ppid pgrp session tty tpgid flags
minflt cminflt majflt cmajflt utime stime cutime cstime priority nice threads
itreal starttime
"""
from pathlib import Path

from folego.core.snapshot import ProcInfo, Snapshot

DEFAULT_MEMINFO = """MemTotal:       14374304 kB
MemFree:          993972 kB
MemAvailable:    6242228 kB
Buffers:          123456 kB
SwapTotal:       7659520 kB
SwapFree:        3743012 kB
"""

DEFAULT_SWAPS = """Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority
/dev/zram1                            partition\t6815744\t\t3984256\t32767
"""

DEFAULT_LOADAVG = "5.04 3.98 2.25 6/1234 3336851\n"

DEFAULT_PRESSURE_MEMORY = "some avg10=0.00 avg60=0.00 avg300=0.00 total=81109886\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=77447214\n"


def pid_dir(root: Path, pid: int, *, comm="app", state="S", ppid=1, pgid=None,
            session=None, utime=100, stime=50, starttime=12345,
            rss_kb=1024, swap_kb=0, uid=1000, cmdline=None):
    d = root / str(pid)
    d.mkdir()
    stat = (f"{pid} ({comm}) {state} {ppid} {pgid if pgid is not None else pid} "
            f"{session if session is not None else pid} "
            f"0 0 0 0 0 0 0 {utime} {stime} 0 0 20 0 1 0 {starttime}")
    (d / "stat").write_text(stat + "\n")
    (d / "comm").write_text(comm + "\n")
    (d / "status").write_text(
        f"Name:\t{comm}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n"
        f"VmRSS:\t{rss_kb} kB\nVmSwap:\t{swap_kb} kB\n")
    cmd = cmdline or [f"/usr/bin/{comm}", "--flag"]
    (d / "cmdline").write_bytes(("\0".join(cmd) + "\0").encode())
    return d


def build_proc(root: Path, *, meminfo=DEFAULT_MEMINFO, swaps=DEFAULT_SWAPS,
               loadavg=DEFAULT_LOADAVG, pressure_memory=DEFAULT_PRESSURE_MEMORY,
               pids=()):
    root.mkdir(parents=True, exist_ok=True)
    (root / "pressure").mkdir(parents=True, exist_ok=True)
    if meminfo is not None:
        (root / "meminfo").write_text(meminfo)
    if swaps is not None:
        (root / "swaps").write_text(swaps)
    if loadavg is not None:
        (root / "loadavg").write_text(loadavg)
    if pressure_memory is not None:
        (root / "pressure" / "memory").write_text(pressure_memory)
    for kw in pids:
        pid_dir(root, **kw)
    return root


def set_proc_fields(root: Path, pid: int, *, utime=None, stime=None,
                    starttime=None, state=None) -> None:
    """Reescreve só os campos pedidos do stat, preservando o layout real."""
    path = root / str(pid) / "stat"
    raw = path.read_text()
    head, rest = raw.split("(", 1)
    comm, rest = rest.rsplit(")", 1)
    fields = rest.split()
    if state is not None:
        fields[0] = state
    if utime is not None:
        fields[11] = str(utime)
    if stime is not None:
        fields[12] = str(stime)
    if starttime is not None:
        fields[19] = str(starttime)
    path.write_text(f"{head}({comm}) {' '.join(fields)}\n")


def set_proc_io(root: Path, pid: int, *, read_bytes=0, write_bytes=0) -> None:
    (root / str(pid) / "io").write_text(
        f"rchar: 999\nwchar: 999\nsyscr: 1\nsyscw: 1\n"
        f"read_bytes: {read_bytes}\nwrite_bytes: {write_bytes}\n")


def set_cpu_stat(root: Path, *, user=0, nice=0, system=0, idle=0, iowait=0,
                 irq=0, softirq=0, steal=0, extra_cpus=0) -> None:
    lines = [f"cpu  {user} {nice} {system} {idle} {iowait} {irq} {softirq} {steal} 0 0"]
    for index in range(extra_cpus):
        lines.append(f"cpu{index} 0 0 0 0 0 0 0 0 0 0")
    (root / "stat").write_text("\n".join(lines) + "\n")


def proc_info(pid, *, comm="app", state="S", ppid=1, pgid=None, session=None,
              utime=100, stime=50, starttime=12345, rss_kb=1024, swap_kb=0,
              uid=1000, cmdline=None, cpu_frac=None) -> ProcInfo:
    """In-memory ProcInfo with the same defaults as pid_dir (leader by default)."""
    return ProcInfo(pid=pid, comm=comm, state=state, ppid=ppid,
                    pgrp=pid if pgid is None else pgid,
                    session=pid if session is None else session,
                    utime=utime, stime=stime, starttime=starttime,
                    rss_kb=rss_kb, swap_kb=swap_kb, uid=uid,
                    cmdline=tuple(cmdline or [f"/usr/bin/{comm}", "--flag"]),
                    cpu_frac=cpu_frac)


def snapshot_of(*procs, ts=1_000.0) -> Snapshot:
    return Snapshot(ts=ts, mem=None, swap_used_kb=0, swap_total_kb=0,
                    pressure_memory=None, pressure_io=None, pressure_cpu=None,
                    load=None, apps=(), self_rss_kb=0, procs=tuple(procs))
