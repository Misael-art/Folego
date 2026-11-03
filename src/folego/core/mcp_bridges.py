"""MCP bridges: stdio→HTTP adapters (`mcp-remote`) and the client that owns each. No Qt, no effects.

A bridge is the npm launcher whose title carries `mcp-remote` and the endpoint,
plus its node child. Its owner is the first ancestor that is not a launcher
wrapper (`disclaimer`, `npm`, `sh`). The server behind the endpoint is separate
and is never part of a bridge. Two bridges for the same client and endpoint are
duplicates; a bridge whose stdio peer is gone is an orphan. Finding whether the
peer is still held uses `ss -xp` once per scan; when that read fails, the
connection is unknown and nothing is called an orphan.
"""
from __future__ import annotations

import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse

from .snapshot import ProcInfo

WRAPPERS = frozenset({"disclaimer", "npm", "sh", "bash", "dash", "env"})
_SOCKET = re.compile(r"socket:\[(\d+)\]")
_SS_ROW = re.compile(r"\*\s+(\d+)\s+\*\s+(\d+)\s+users:\((.*)\)\s*$")
_PID = re.compile(r"pid=(\d+)")

ORPHAN = "órfã"
DUPLICATE = "duplicada"
SINGLE = "única"
UNKNOWN = "conexão desconhecida"


@dataclass(frozen=True)
class Bridge:
    pid: int                 # npm launcher
    starttime: int
    members: tuple[ProcInfo, ...]
    endpoint: str
    client_pid: int | None
    client: str
    connected: bool | None   # stdio peer held by a process outside the bridge
    rss_kb: int
    cpu_frac: float | None
    status: str = SINGLE

    @property
    def key(self) -> tuple:
        return (self.client_pid, self.endpoint)


def _endpoint(proc: ProcInfo) -> str:
    for part in " ".join(proc.cmdline).split():
        if part.startswith(("http://", "https://")):
            return part
    return ""


def is_launcher(proc: ProcInfo) -> bool:
    return bool(proc.cmdline) and proc.cmdline[0].startswith("npm") and "mcp-remote" in " ".join(proc.cmdline)


def socket_peers(run=subprocess.run) -> dict[int, set[int]] | None:
    """inode -> pids holding the *peer* end of that unix socket; None when unreadable."""
    binary = shutil.which("ss")
    if not binary:
        return None
    try:
        done = run([binary, "-xpH"], capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    holders: dict[int, set[int]] = {}
    peer_of: dict[int, int] = {}
    for line in done.stdout.splitlines():
        match = _SS_ROW.search(line)
        if not match:
            continue
        local, peer = int(match.group(1)), int(match.group(2))
        peer_of[local] = peer
        holders.setdefault(local, set()).update(int(p) for p in _PID.findall(match.group(3)))
    return {inode: holders.get(peer, set()) for inode, peer in peer_of.items()}


def _stdin_inode(pid: int, proc_root: str) -> int | None:
    import os
    try:
        match = _SOCKET.match(os.readlink(f"{proc_root}/{pid}/fd/0"))
    except OSError:
        return None
    return int(match.group(1)) if match else None


def scan(procs, *, peers: dict | None, proc_root: str = "/proc", stdin_fn=None) -> tuple[Bridge, ...]:
    procs = list(procs)
    by_pid = {p.pid: p for p in procs}
    children: dict[int, list[ProcInfo]] = {}
    for p in procs:
        children.setdefault(p.ppid, []).append(p)
    stdin_fn = stdin_fn or (lambda pid: _stdin_inode(pid, proc_root))
    found = []
    for launcher in (p for p in procs if is_launcher(p)):
        members = (launcher, *children.get(launcher.pid, ()))
        own = {m.pid for m in members}
        client = by_pid.get(launcher.ppid)
        while client is not None and client.comm in WRAPPERS:
            own.add(client.pid)
            client = by_pid.get(client.ppid)
        connected = None
        inode = stdin_fn(launcher.pid)
        if peers is not None and inode is not None:
            connected = bool(peers.get(inode, set()) - own)
        fractions = [m.cpu_frac for m in members if m.cpu_frac is not None]
        found.append(Bridge(launcher.pid, launcher.starttime, tuple(members), _endpoint(launcher),
                            client.pid if client else None, client.comm if client else "?",
                            connected, sum(m.rss_kb for m in members),
                            sum(fractions) if fractions else None))
    counts: dict[tuple, int] = {}
    for bridge in found:
        if bridge.connected is not False:
            counts[bridge.key] = counts.get(bridge.key, 0) + 1
    out = []
    for bridge in found:
        if bridge.connected is False:
            status = ORPHAN
        elif counts.get(bridge.key, 0) > 1:
            status = DUPLICATE if bridge.connected else UNKNOWN
        else:
            status = SINGLE if bridge.connected else UNKNOWN
        out.append(Bridge(**{**bridge.__dict__, "status": status}))
    out.sort(key=lambda b: (b.key, b.starttime))
    return tuple(out)


def stoppable(bridge: Bridge, bridges) -> tuple[bool, str]:
    """Only an orphan, or a duplicate that leaves another connected bridge for its client."""
    if bridge.status == ORPHAN:
        return True, "órfã: o cliente já fechou a conexão"
    others = [b for b in bridges if b.key == bridge.key and b.pid != bridge.pid and b.connected]
    if bridge.status == DUPLICATE and others:
        return True, f"outra ponte do mesmo cliente continua conectada (pid {others[0].pid})"
    return False, "é a única ponte conectada deste cliente; finalizar desligaria o MCP dele"


def endpoint_alive(endpoint: str, timeout: float = 1.0) -> bool | None:
    """Only loopback endpoints are probed (TCP connect); remote ones are not touched."""
    url = urlparse(endpoint)
    if url.hostname not in ("127.0.0.1", "localhost", "::1") or not url.port:
        return None
    try:
        with socket.create_connection((url.hostname, url.port), timeout=timeout):
            return True
    except OSError:
        return False
