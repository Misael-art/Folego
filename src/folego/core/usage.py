"""Is someone using this app right now? Evidence that protects a group. No Qt, no effects.

Four signals, each cheap and read fresh: the focused window's PID (kdotool on
KWin), audio streams by PID (pactl), downloads in progress and project files
open for writing (both from /proc/<pid>/fd). A probe that cannot answer is
reported as such; for focus and audio "unknown" protects, because the effect
would be the one thing nobody can undo.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable

DOWNLOAD_SUFFIXES = (".crdownload", ".part", ".partial", ".download")
_WRITE = os.O_WRONLY | os.O_RDWR
TIMEOUT_S = 3


@dataclass(frozen=True)
class Probes:
    focused: int | None | str     # pid, None (no window) or a reason string when unknown
    audio: frozenset[int] | str   # pids with a playing stream, or a reason string


def focused_pid(run=subprocess.run) -> int | None | str:
    binary = shutil.which("kdotool")
    if not binary:
        return "foco desconhecido: kdotool ausente"
    try:
        done = run([binary, "getactivewindow", "getwindowpid"], capture_output=True, text=True,
                   timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"foco desconhecido: {exc}"
    text = done.stdout.strip().splitlines()
    if done.returncode != 0:
        return "foco desconhecido: kdotool falhou"
    if not text:
        return "foco desconhecido: resposta vazia"
    try:
        pid = int(text[-1])
    except ValueError:
        return "foco desconhecido: resposta inesperada"
    return pid if pid > 0 else "foco desconhecido: PID inválido"


def audio_pids(run=subprocess.run) -> frozenset[int] | str:
    binary = shutil.which("pactl")
    if not binary:
        return "áudio desconhecido: pactl ausente"
    try:
        done = run([binary, "-f", "json", "list", "sink-inputs"], capture_output=True, text=True,
                   timeout=TIMEOUT_S, check=False)
        streams = json.loads(done.stdout or "[]") if done.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return f"áudio desconhecido: {exc}"
    if streams is None:
        return "áudio desconhecido: pactl falhou"
    if not isinstance(streams, list):
        return "áudio desconhecido: resposta inesperada"
    pids = set()
    for stream in streams:
        if not isinstance(stream, dict):
            return "áudio desconhecido: stream inesperado"
        if stream.get("corked"):
            continue
        try:
            pid = int(stream.get("properties", {}).get("application.process.id"))
        except (AttributeError, TypeError, ValueError):
            return "áudio desconhecido: stream ativo sem PID"
        if pid <= 0:
            return "áudio desconhecido: PID inválido"
        pids.add(pid)
    return frozenset(pids)


def probe(run=subprocess.run) -> Probes:
    return Probes(focused_pid(run), audio_pids(run))


def _open_files(pid: int, proc_root: str) -> Iterable[tuple[str, int]]:
    base = f"{proc_root}/{pid}"
    fds = os.listdir(f"{base}/fd")
    for fd in fds:
        target = os.readlink(f"{base}/fd/{fd}")
        if not target.startswith("/"):
            continue
        flags = None
        with open(f"{base}/fdinfo/{fd}") as info:
            for line in info:
                if line.startswith("flags:"):
                    parts = line.split()
                    if len(parts) != 2:
                        raise ValueError(f"fdinfo sem flags válidas: {pid}/{fd}")
                    flags = int(parts[1], 8)
                    break
        if flags is None:
            raise ValueError(f"fdinfo sem flags: {pid}/{fd}")
        yield target, flags


def in_use(pids: Iterable[int], *, probes: Probes, projects: Iterable[str],
           proc_root: str = "/proc", files: Callable = _open_files) -> str | None:
    """Reason the group is in use, or None. Unknown focus/audio protects."""
    members = set(pids)
    if isinstance(probes.focused, str):
        return probes.focused
    if probes.focused in members:
        return "janela em foco"
    if isinstance(probes.audio, str):
        return probes.audio
    if members & probes.audio:
        return "tocando áudio"
    roots = tuple(p.rstrip("/") + "/" for p in projects)
    try:
        for pid in members:
            for target, flags in files(pid, proc_root):
                if target.removesuffix(" (deleted)").endswith(DOWNLOAD_SUFFIXES):
                    return "download em andamento"
                if flags & _WRITE and roots and target.startswith(roots):
                    return "arquivo de projeto aberto para escrita"
    except (OSError, ValueError) as exc:
        return f"arquivos abertos desconhecidos: {exc}"
    return None
