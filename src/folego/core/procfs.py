"""Read-only /proc parsers. Every reader degrades to None on a missing or
malformed file — one absent knob never voids a snapshot."""
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from .snapshot import CpuTimes, LoadAvg, MemInfo, Pressure, ProcInfo, SwapInfo


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
            try:
                fields[key.strip()] = int(parts[0])
            except ValueError:
                continue  # campo malformado não esconde os legíveis (F1.8/R16)
    if "MemTotal" not in fields or "MemAvailable" not in fields:
        return None
    return MemInfo(fields["MemTotal"], fields["MemAvailable"])


def read_pressure(root: Path | None = None, source: str = "memory") -> Pressure | None:
    raw = _read(root or Path(paths.proc_root()), f"pressure/{source}")
    if raw is None:
        return None
    some = full = None
    for line in raw.splitlines():
        parts = line.split()
        if not parts or parts[0] not in ("some", "full"):
            continue
        kv = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        try:
            parsed = (float(kv["avg10"]), float(kv["avg60"]),
                      float(kv["avg300"]), int(kv["total"]))
        except (KeyError, ValueError):
            if parts[0] == "some":
                return None
            continue
        if parts[0] == "some":
            some = parsed
        else:
            full = parsed
    if some is None:
        return None
    return Pressure(
        *some,
        full_avg10=full[0] if full else None,
        full_avg60=full[1] if full else None,
        full_avg300=full[2] if full else None,
        full_total=full[3] if full else None,
    )


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


def read_cpu_times(root: Path | None = None) -> CpuTimes | None:
    raw = _read(root or Path(paths.proc_root()), "stat")
    if raw is None:
        return None
    for line in raw.splitlines():
        parts = line.split()
        if not parts or parts[0] != "cpu":
            continue
        try:
            values = [int(part) for part in parts[1:9]]
        except ValueError:
            return None
        # kernels antigos podem omitir iowait/irq/softirq/steal; zero é o valor
        # que o próprio kernel reporta para campo ausente, mas o total observado
        # continua sendo a soma do que veio.
        values += [0] * (8 - len(values))
        return CpuTimes(*values[:8])
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
        # Layout real de /proc/<pid>/stat depois do comm (base 0):
        # state ppid pgrp session tty tpgid flags minflt cminflt majflt
        # cmajflt utime stime cutime cstime priority nice threads itreal starttime
        return (int(head), f[0], int(f[1]), int(f[2]), int(f[3]),
                int(f[11]), int(f[12]), int(f[19]))
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
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            if parts[0] == "VmRSS:":
                rss_kb = int(parts[1])
            elif parts[0] == "VmSwap:":
                swap_kb = int(parts[1])
            elif parts[0] == "Uid:":
                uid = int(parts[1])
        except ValueError:
            continue  # campo malformado degrada para zero, não anula a amostra
    comm = ""
    try:
        comm = (root / str(pid) / "comm").read_text().strip()
    except OSError:
        pass  # o comm pode sumir entre exists() e read_text(): cai para o cmdline
    cmdline = tuple(c.decode("utf-8", "replace") for c in cmdline_raw.split(b"\0") if c)
    if not comm and cmdline:
        comm = cmdline[0].rsplit("/", 1)[-1]
    io_read, io_write = _read_proc_io(root, pid)
    return ProcInfo(pid_, comm, state, ppid, pgrp, session, utime, stime, starttime,
                    rss_kb, swap_kb, uid, cmdline,
                    io_read_bytes=io_read, io_write_bytes=io_write)


def _read_proc_io(root: Path, pid: int) -> tuple[int | None, int | None]:
    """Bytes de disco acumulados; EACCES em processo de outro dono vira None."""
    try:
        raw = (root / str(pid) / "io").read_text()
    except OSError:
        return None, None
    fields = {}
    for line in raw.splitlines():
        key, _, rest = line.partition(":")
        try:
            fields[key.strip()] = int(rest.split()[0])
        except (IndexError, ValueError):
            continue
    return fields.get("read_bytes"), fields.get("write_bytes")


def read_pss_kb(root: Path, pid: int) -> int | None:
    """PSS sob demanda: só chamado quando alguém pede, nunca no poll de 2 s.

    Prefere `smaps_rollup` (uma linha Pss:, leitura curta); cai para `smaps`
    somando as linhas Pss. Sem permissão, devolve None — não zero.
    """
    directory = root / str(pid)
    smaps_rollup = directory / "smaps_rollup"
    try:
        raw = smaps_rollup.read_text()
    except OSError:
        raw = None
    if raw is not None:
        for line in raw.splitlines():
            if line.startswith("Pss:"):
                try:
                    return int(line.split()[1])
                except (IndexError, ValueError):
                    return None
        return None
    try:
        raw = (directory / "smaps").read_text()
    except OSError:
        return None
    total = 0
    found = False
    for line in raw.splitlines():
        if not line.startswith("Pss:"):
            continue
        try:
            total += int(line.split()[1])
            found = True
        except (IndexError, ValueError):
            return None
    return total if found else None


@dataclass(frozen=True)
class ProcScan:
    """Resultado de uma varredura: vazio por ausência nunca é vazio provado."""

    procs: tuple[ProcInfo, ...] = ()
    entries: int = 0
    unreadable: tuple[int, ...] = ()
    error: str | None = None
    truncated: bool = False


def scan_processes(root: Path | None = None, *, limit: int = 0) -> ProcScan:
    root = root or Path(paths.proc_root())
    try:
        names = [n for n in root.iterdir() if n.name.isdigit()]
    except OSError as exc:
        return ProcScan(error=f"{type(exc).__name__}: {exc}")
    names.sort(key=lambda item: int(item.name))
    total = len(names)
    truncated = limit > 0 and total > limit
    if truncated:
        names = names[:limit]
    out = []
    unreadable = []
    for n in names:
        info = read_proc(root, int(n.name))
        if info is not None:
            out.append(info)
        else:
            # Se o stat ainda está lá, o processo não sumiu: a entrada é
            # ilegível. Se sumiu no meio da varredura, é corrida normal.
            try:
                (root / n.name).stat()
                still_there = True
            except FileNotFoundError:
                still_there = False
            except OSError:
                still_there = True
            if still_there:
                unreadable.append(int(n.name))
    return ProcScan(tuple(out), total, tuple(unreadable), None, truncated)


def list_processes(root: Path | None = None) -> list[ProcInfo]:
    return list(scan_processes(root).procs)
