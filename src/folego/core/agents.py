"""Which processes are doing agent work right now. Pure Python, no Qt, no effects.

The Performance mode may only ever close what is *not* serving an agent, so this
module answers the protective question first. It is deliberately generous: an
agent root protects its whole ancestry and descendants, and any process whose
working directory sits inside a Git work tree is treated as project work.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .snapshot import ProcInfo

# Agent roots by kernel comm; desktop clients by a stable fragment of their exe path.
AGENT_COMMS = frozenset({"claude", "codex", "codex-web-gpt-l", "claude-desktop"})
AGENT_PATH_MARKERS = ("/claude-desktop/", "/chatgpt-web/", "/claude-code/", "/codex/")

IDLE = "idle"
INTERACTIVE = "interactive"
BUSY = "busy"
# Summed CPU of the protected trees, in percent of one CPU (collector unit).
BUSY_CPU = 150.0
INTERACTIVE_CPU = 5.0


@dataclass(frozen=True)
class AgentActivity:
    roots: frozenset[int]
    protected: frozenset[int]
    projects: frozenset[str]
    load: str
    cpu_frac: float | None

    def protects(self, pid: int) -> bool:
        return pid in self.protected


def is_agent_root(proc: ProcInfo) -> bool:
    if proc.comm in AGENT_COMMS:
        return True
    exe = proc.cmdline[0] if proc.cmdline else ""
    return any(marker in exe for marker in AGENT_PATH_MARKERS)


def git_root(path: str | None, cache: dict[str, str | None]) -> str | None:
    """Closest directory holding `.git`, or None; memoized per directory."""
    if not path or not path.startswith("/"):
        return None
    if path in cache:
        return cache[path]
    found = None
    current = Path(path)
    for candidate in (current, *current.parents):
        try:
            if (candidate / ".git").exists():
                found = str(candidate)
                break
        except OSError:
            break  # unreadable ancestry proves nothing; stop instead of guessing
    cache[path] = found
    return found


def detect(procs: Iterable[ProcInfo], *, cwd_fn: Callable[[int], str | None],
           git_cache: dict[str, str | None] | None = None) -> AgentActivity:
    procs = list(procs)
    by_pid = {p.pid: p for p in procs}
    children: dict[int, list[int]] = {}
    for p in procs:
        children.setdefault(p.ppid, []).append(p.pid)
    cache = {} if git_cache is None else git_cache
    roots = {p.pid for p in procs if is_agent_root(p)}
    projects = set()
    for p in procs:
        root = git_root(cwd_fn(p.pid), cache)
        if root is not None:
            projects.add(root)
            roots.add(p.pid)
    protected = set()
    for root in roots:
        stack = [root]
        while stack:
            pid = stack.pop()
            if pid in protected:
                continue
            protected.add(pid)
            stack.extend(children.get(pid, ()))
        parent = by_pid[root].ppid
        while parent > 1 and parent in by_pid and parent not in protected:
            protected.add(parent)
            parent = by_pid[parent].ppid
    fractions = [by_pid[pid].cpu_frac for pid in protected if by_pid[pid].cpu_frac is not None]
    cpu = sum(fractions) if fractions else None
    if cpu is None:
        load = INTERACTIVE if protected else IDLE  # unmeasured work is never idle
    elif cpu >= BUSY_CPU:
        load = BUSY
    elif cpu >= INTERACTIVE_CPU:
        load = INTERACTIVE
    else:
        load = IDLE
    return AgentActivity(frozenset(roots), frozenset(protected), frozenset(projects), load, cpu)
