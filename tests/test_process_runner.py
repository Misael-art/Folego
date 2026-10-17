"""M2 harness: a mutation runs in a child process, never in the tray.

The Deck has real D-state hazards (the sdcard that throws EIO, a browser mid-
fsync). A parent that waits on such a write stops polling, stops drawing, and
looks dead to the user — so the parent waits with a timeout, and when the child
does not answer it is SIGKILLed and the parent returns its verdict anyway.
"""
import os
import sys
import threading
import time

import pytest

from folego.process.runner import run_isolated

PYTHON = sys.executable


def test_a_finished_command_reports_its_exit_and_output():
    result = run_isolated([PYTHON, "-c", "print('oi')"], timeout=10)

    assert result.ok and result.exit_code == 0
    assert result.stdout.strip() == "oi"
    assert result.timed_out is False


def test_a_failing_child_reports_its_stderr_rather_than_a_lie():
    result = run_isolated(
        [PYTHON, "-c", "import sys; sys.stderr.write('quebrou'); sys.exit(3)"], timeout=10)

    assert result.ok is False and result.exit_code == 3
    assert "quebrou" in result.stderr


def test_a_child_that_never_ends_is_killed_and_the_parent_comes_back():
    started = time.monotonic()

    result = run_isolated([PYTHON, "-c", "import time; time.sleep(30)"], timeout=0.4)

    waited = time.monotonic() - started
    assert result.timed_out and not result.ok
    assert waited < 5, f"o pai bloqueou por {waited:.1f}s"
    assert result.pid
    with pytest.raises(ProcessLookupError):
        os.kill(result.pid, 0)


def test_a_child_that_prints_more_than_the_pipe_holds_still_exits():
    """stdout is a pipe: a chatty child must not deadlock the parent while it
    waits on a full buffer."""
    result = run_isolated([PYTHON, "-c", "print('x' * 4_000_000)"], timeout=20)

    assert result.ok and len(result.stdout.strip()) == 4_000_000


def test_one_mutation_at_a_time_a_second_request_is_refused_not_queued():
    lock = threading.Lock()
    lock.acquire()

    refused = run_isolated([PYTHON, "-c", "print('não roda')"], timeout=5, lock=lock)

    assert refused.refused and "em voo" in refused.refused
    assert refused.stdout == "" and refused.pid is None

    lock.release()
    second = run_isolated([PYTHON, "-c", "print('roda')"], timeout=5, lock=lock)

    assert second.ok and second.stdout.strip() == "roda"
