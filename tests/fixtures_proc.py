"""Builder for fake /proc trees used by collector tests.

stat field layout after ')' (0-based): state ppid pgrp session tty flags
minflt cminflt majflt cmajflt utime stime prio nice nthr itreal starttime
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
            f"0 0 0 0 0 0 {utime} {stime} 0 0 0 0 {starttime}")
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


def proc_info(pid, *, comm="app", state="S", ppid=1, pgid=None, session=None,
              utime=100, stime=50, starttime=12345, rss_kb=1024, swap_kb=0,
              uid=1000, cmdline=None) -> ProcInfo:
    """In-memory ProcInfo with the same defaults as pid_dir (leader by default)."""
    return ProcInfo(pid=pid, comm=comm, state=state, ppid=ppid,
                    pgrp=pid if pgid is None else pgid,
                    session=pid if session is None else session,
                    utime=utime, stime=stime, starttime=starttime,
                    rss_kb=rss_kb, swap_kb=swap_kb, uid=uid,
                    cmdline=tuple(cmdline or [f"/usr/bin/{comm}", "--flag"]))


def snapshot_of(*procs, ts=1_000.0) -> Snapshot:
    return Snapshot(ts=ts, mem=None, swap_used_kb=0, swap_total_kb=0,
                    pressure_memory=None, pressure_io=None, pressure_cpu=None,
                    load=None, apps=(), self_rss_kb=0, procs=tuple(procs))
