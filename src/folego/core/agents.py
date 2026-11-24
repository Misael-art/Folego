"""Which processes are doing agent work right now. Pure Python, no Qt, no effects.

The Performance mode may only ever close what is *not* serving an agent, so this
module answers the protective question first. It is deliberately generous: an
agent root protects its whole ancestry and descendants, and any process whose
working directory sits inside a Git work tree is treated as project work.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Callable, Iterable

from .snapshot import ProcInfo

# Agent roots by kernel comm; desktop clients by a stable fragment of their exe path.
AGENT_COMMS = frozenset({"claude", "codex", "codex-web-gpt-l", "claude-desktop"})
# /lib/chatgpt/ is the official OpenAI desktop app (Arch package chatgpt-bin, /usr/lib/chatgpt/ChatGPT),
# which hosts Codex Desktop; its Electron tree runs the bundled `codex app-server`.
AGENT_PATH_MARKERS = ("/claude-desktop/", "/chatgpt-web/", "/claude-code/", "/codex/", "/lib/chatgpt/")
# A browser opened for automation (CDP or Marionette) is driven by some agent.
# Only real browsers count: apps such as Steam embed Chromium with CDP for themselves.
AUTOMATION_FLAGS = ("--remote-debugging-port", "--remote-debugging-pipe", "--marionette")
BROWSER_COMMS = frozenset({"msedge", "chrome", "chromium", "google-chrome", "brave", "firefox",
                           "firefox-bin", "vivaldi-bin", "opera"})

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
    if any(marker in exe for marker in AGENT_PATH_MARKERS):
        return True
    return proc.comm in BROWSER_COMMS and any(arg.startswith(AUTOMATION_FLAGS)
                                               for arg in proc.cmdline[1:])


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


# ------------------------------------------------------------ per-agent footprint

# Main binary per provider; desktop apps are recognised by the same path markers as is_agent_root.
PROVIDER_COMMS = {"codex": "codex", "codex-web-gpt-l": "codex", "claude": "claude", "claude-desktop": "claude"}
PROVIDER_MARKERS = (("/lib/chatgpt/", "codex"), ("/chatgpt-web/", "codex"), ("/codex/", "codex"),
                    ("/claude-desktop/", "claude"), ("/claude-code/", "claude"))
MAIN_COMMS = {"codex": "codex", "claude": "claude"}
# An MCP server names itself in its program or package (mcp-remote, @modelcontextprotocol/...,
# server-mcp); a bare substring would match random Electron arguments.
MCP_WORD = re.compile(r"(?:^|[/@_.-])mcp(?:[/@_.-]|$)|modelcontextprotocol", re.IGNORECASE)


RUNNERS = frozenset({"node", "npx", "npm", "pnpm", "bun", "bunx", "deno", "uv", "uvx", "python", "python3"})


def argv(proc: ProcInfo) -> tuple[str, ...]:
    """Chromium/Electron rewrite argv into one space-joined string; split it back."""
    if len(proc.cmdline) == 1 and " " in proc.cmdline[0]:
        return tuple(proc.cmdline[0].split())
    return proc.cmdline


def is_helper(proc: ProcInfo) -> bool:
    """Chromium/Electron children and crash handlers are part of an app, not separate instances."""
    args = argv(proc)
    # comm is cut at 15 bytes (browser_crashpa); the program path is not.
    return ("crashpad" in (args[0].rsplit("/", 1)[-1] if args else proc.comm)
            or any(arg.startswith("--type=") for arg in args[1:]))


def is_mcp_server(proc: ProcInfo) -> bool:
    """By program or package name only; a shell whose script mentions MCP is not a server."""
    args = argv(proc)
    if not args or is_helper(proc):
        return False
    program = args[0].rsplit("/", 1)[-1]
    names = [program] + (list(args[1:4]) if program in RUNNERS else [])
    return any(MCP_WORD.search(name) for name in names)


def provider_of(proc: ProcInfo) -> str | None:
    """Which agent a root belongs to; browsers driven over CDP count as `automation`."""
    if not is_agent_root(proc):
        return None
    if proc.comm in PROVIDER_COMMS:
        return PROVIDER_COMMS[proc.comm]
    exe = proc.cmdline[0] if proc.cmdline else ""
    for marker, provider in PROVIDER_MARKERS:
        if marker in exe:
            return provider
    return "automation"


def footprint(procs: Iterable[ProcInfo]) -> dict[str, dict]:
    """Count and size each agent's process trees, for the host history.

    Each process belongs to its nearest agent root (itself included), so a Codex
    started by Claude Code counts as Codex. `top` counts roots with no ancestor of
    the same provider: independent instances. CPU is the sum of measured members in
    percent of one core (None while no member has a delta yet). Pure: no /proc reads.
    """
    procs = list(procs)
    by_pid = {p.pid: p for p in procs}
    owner: dict[int, str | None] = {}

    def nearest(pid: int) -> str | None:
        chain, current, found = [], pid, None
        for _ in range(64):
            if current in owner:
                found = owner[current]
                break
            proc = by_pid.get(current)
            if proc is None:
                break
            chain.append(current)
            found = provider_of(proc)
            if found is not None or proc.ppid in (0, current):
                break
            current = proc.ppid
        for item in chain:
            owner[item] = found
        return found

    result: dict[str, dict] = {}
    for proc in procs:
        provider = nearest(proc.pid)
        if provider is None:
            continue
        row = result.setdefault(provider, {"procs": 0, "main": 0, "top": 0, "app_server": 0,
                                           "exec_server": 0, "exec": 0, "mcp": 0, "rss_kb": 0,
                                           "cpu_pct": None})
        row["procs"] += 1
        row["rss_kb"] += proc.rss_kb
        if proc.cpu_frac is not None:
            row["cpu_pct"] = round((row["cpu_pct"] or 0.0) + proc.cpu_frac, 1)
        args = argv(proc)[1:]
        if proc.comm == MAIN_COMMS.get(provider):
            row["main"] += 1
            if "exec" in args[:3]:
                row["exec"] += 1
        if "app-server" in args:
            row["app_server"] += 1
        if "exec-server" in args:
            row["exec_server"] += 1
        if is_mcp_server(proc):
            row["mcp"] += 1
        if (provider_of(proc) == provider and not is_helper(proc)
                and (proc.ppid not in by_pid or nearest(proc.ppid) != provider)):
            row["top"] += 1
    return result
