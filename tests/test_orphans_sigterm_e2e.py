"""Entrega 8: SIGTERM de verdade, contra processos de fixture do próprio teste.

O alvo é sempre um filho ``python -c`` criado aqui (nunca um processo do host): o
teste prova que o sinal sai, que a saída é **observada** antes de dizer
"encerrado" e que sobreviver ao SIGTERM não dispara SIGKILL sozinho.
"""
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from folego.actions.orphans.reaper import Reaper
from folego.core import procfs
from folego.core.orphans import OrphanCandidate
from folego.safely import procs

PROC = Path("/proc")


@pytest.fixture
def spawn():
    children = []

    def _spawn(*, ignore_term=False, browser_identity=False):
        code = "import time; print('ready', flush=True); time.sleep(60)"
        if ignore_term:
            code = ("import signal, time; "
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    "print('ready', flush=True); time.sleep(60)")
        child = subprocess.Popen(["/opt/microsoft/msedge/msedge" if browser_identity else sys.executable, "-c", code],
                                 executable=sys.executable,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True)
        children.append(child)
        assert select.select([child.stdout], [], [], 5.0)[0], \
            "o filho não ficou pronto"
        assert child.stdout.readline().strip() == "ready"
        child.stdout.close()
        live = procfs.read_proc(PROC, child.pid)
        assert live is not None, "o filho não apareceu no /proc"
        return child, live

    yield _spawn

    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


def target_of(live):
    return OrphanCandidate(pid=live.pid, comm=live.comm, state=live.state,
                           uid=live.uid, rss_kb=live.rss_kb, swap_kb=live.swap_kb,
                           starttime=live.starttime, idle_s=0.0, ppid=live.ppid)


def test_sigterm_is_observed_until_the_child_is_gone(spawn):
    child, live = spawn()
    pinned = procs.pin(child.pid)
    method = pinned.method
    procs.close(pinned)

    reaper = Reaper(follow_up_s=3.0, poll_s=0.02)
    result = reaper.terminate(target_of(live), require_orphan=False)

    assert result.ok and result.signal == signal.SIGTERM
    assert result.exited is True, "só depois de observar a saída"
    assert result.identity == method, "o método do ato é o que o kernel oferece"
    assert child.wait(timeout=5) == -signal.SIGTERM


def test_a_child_that_ignores_sigterm_is_named_and_sigkill_is_separate(spawn):
    child, live = spawn(ignore_term=True)
    reaper = Reaper(follow_up_s=0.4, poll_s=0.02)

    result = reaper.terminate(target_of(live), require_orphan=False)

    assert result.ok and result.exited is False
    assert child.poll() is None, "ignorou o SIGTERM de propósito"

    killed = reaper.force(target_of(live), confirm=True, require_orphan=False)

    assert killed.ok and killed.signal == signal.SIGKILL and killed.exited is True
    assert child.wait(timeout=5) == -signal.SIGKILL


def test_coordinated_cli_only_signals_the_child_created_by_this_test(spawn, fake_home, capsys):
    import json
    from folego import cli
    from folego.actions.orphans.coordinated import plan_for
    from folego.core.sessions import read_boot_id
    from folego.orchestration import Journal
    child, live = spawn(browser_identity=True)
    assert live.cmdline[0] == "/opt/microsoft/msedge/msedge"
    plan = plan_for([target_of(live)], boot_id=read_boot_id(), require_orphan=False, group="edge")
    assert cli.main(["process", "--plan", json.dumps(plan.to_dict()), "--confirmar", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation_id"] == plan.operation_id
    assert payload["effects"]["results"][0]["exited"] is True
    assert child.wait(timeout=5) == -signal.SIGTERM
    state = Journal().state_of(plan.operation_id)
    assert state.intent is not None and state.result.ok
