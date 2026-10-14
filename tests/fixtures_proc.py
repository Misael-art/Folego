"""Builder for fake /proc trees used by collector tests.

stat field layout after ')' (0-based): state ppid pgrp session tty flags
minflt cminflt majflt cmajflt utime stime prio nice nthr itreal starttime
"""
from pathlib import Path

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
    (root / "pressure").mkdir(exist_ok=True)
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
