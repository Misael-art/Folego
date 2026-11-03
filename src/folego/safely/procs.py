"""Identidade de processo no ato do sinal: pidfd quando houver, starttime sempre.

Entre a amostra que mostrou o processo e o clique, o PID pode ser reciclado. O
Reaper relê ``/proc/<pid>`` e compara o starttime; abrir o pidfd **antes** da
releitura fecha a janela entre a checagem e o sinal: o fd aponta para o processo
que existia quando foi aberto, então um PID reciclado depois não recebe o sinal.
Sem pidfd (kernel antigo), o chamador revalida o starttime imediatamente antes de
``os.kill`` — o caminho manual continua, com a janela residual nomeada no
resultado (``identity="starttime"``). Automação segue desligada; quando ligar,
exigir pidfd é decisão de F6.
"""
from __future__ import annotations

import errno
import os
import signal
from dataclasses import dataclass

# ENOSYS/EINVAL: kernel ou arquitetura sem o syscall de pidfd. EPERM não é "sem
# suporte" — é política, e tem de aparecer como falha, nunca virar fallback mudo.
_UNSUPPORTED = {errno.ENOSYS, errno.EINVAL}


@dataclass(frozen=True)
class Pin:
    """O fd que pina o processo, ou a declaração de que o kernel não o oferece."""

    pid: int
    fd: int | None
    supported: bool

    @property
    def method(self) -> str:
        return "pidfd" if self.supported else "starttime"


def unsupported(pid: int) -> Pin:
    """Costura para árvores /proc falsas: sem fd real, identidade por starttime."""
    return Pin(pid=pid, fd=None, supported=False)


def pin(pid: int, *, pidfd_open=None) -> Pin:
    """Pina o pid; levanta ProcessLookupError se ele já não existe."""
    opener = pidfd_open if pidfd_open is not None else getattr(os, "pidfd_open", None)
    if opener is None or not hasattr(signal, "pidfd_send_signal"):
        return Pin(pid, None, False)
    try:
        fd = opener(pid)
    except OSError as err:
        if err.errno in _UNSUPPORTED:
            return Pin(pid, None, False)
        raise
    return Pin(pid, fd, True)


def send(pinned: Pin, sig: int, *, kill_fn=os.kill) -> None:
    """Sinaliza o processo pinado; no fallback, ``kill_fn`` fala com o pid."""
    if pinned.fd is not None:
        signal.pidfd_send_signal(pinned.fd, sig)
    else:
        kill_fn(pinned.pid, sig)


def close(pinned: Pin) -> None:
    if pinned.fd is not None:
        try:
            os.close(pinned.fd)
        except OSError:
            pass
