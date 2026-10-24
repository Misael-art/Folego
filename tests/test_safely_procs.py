"""Entrega 8: o sinal vai para o processo verificado, não para o número do pid.

O pidfd é aberto **antes** da releitura do /proc; quando o kernel não oferece o
syscall, o fallback é starttime + kill e o resultado nomeia o método. Nada aqui
toca um processo real: os fds são de um pipe e o envio é capturado.
"""
import errno
import os
import signal

import pytest

from folego.safely import procs


def test_pin_reports_unsupported_when_the_kernel_lacks_the_syscall():
    def opener(pid):
        raise OSError(errno.ENOSYS, "sem pidfd")

    pinned = procs.pin(123, pidfd_open=opener)

    assert not pinned.supported and pinned.fd is None
    assert pinned.method == "starttime"


@pytest.mark.skipif(not hasattr(signal, "pidfd_send_signal"),
                    reason="kernel/python sem pidfd_send_signal")
def test_pin_opens_the_fd_and_send_goes_through_it(monkeypatch):
    read_fd, write_fd = os.pipe()
    try:
        pinned = procs.pin(123, pidfd_open=lambda pid: read_fd)
        assert pinned.supported and pinned.fd == read_fd
        assert pinned.method == "pidfd"

        seen = []
        monkeypatch.setattr(signal, "pidfd_send_signal",
                            lambda fd, sig: seen.append((fd, sig)))
        procs.send(pinned, signal.SIGTERM)

        assert seen == [(read_fd, signal.SIGTERM)]
        procs.close(pinned)
        with pytest.raises(OSError):
            os.close(read_fd)  # fechou de verdade
    finally:
        for fd in (read_fd, write_fd):
            try:
                os.close(fd)
            except OSError:
                pass


def test_send_falls_back_to_kill_without_pidfd():
    calls = []

    procs.send(procs.unsupported(42), signal.SIGTERM,
               kill_fn=lambda pid, sig: calls.append((pid, sig)))

    assert calls == [(42, signal.SIGTERM)]


def test_pin_raises_when_the_pid_is_already_gone():
    def opener(pid):
        raise ProcessLookupError(errno.ESRCH, "já saiu")

    with pytest.raises(ProcessLookupError):
        procs.pin(1, pidfd_open=opener)


def test_pin_does_not_swallow_real_permission_errors():
    def opener(pid):
        raise PermissionError(errno.EPERM, "política")

    with pytest.raises(PermissionError):
        procs.pin(1, pidfd_open=opener)
