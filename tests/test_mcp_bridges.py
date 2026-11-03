import subprocess
import sys
from pathlib import Path

from folego.actions.orphans.reaper import Reaper
from folego.actions.performance import bridges as actions
from folego.core import mcp_bridges as mb
from folego.core import procfs
from folego.core.snapshot import ProcInfo
from folego.orchestration import Coordinator, Outcome
from folego.orchestration.journal import Journal

URL = "http://127.0.0.1:49374/mcp"


def proc(pid, comm, ppid, cmd, start=None):
    return ProcInfo(pid, comm, "S", ppid, pid, pid, 0, 0, start or pid, 1000, 0, 1000, tuple(cmd), cpu_frac=0.0)


def host():
    return [proc(10, "claude-desktop", 1, ["/x/claude-desktop"]),
            proc(11, "disclaimer", 10, ["disclaimer"]),
            proc(12, "npm exec mcp-re", 11, [f"npm exec mcp-remote@latest {URL}"]),
            proc(13, "node-MainThread", 12, ["node", "mcp-remote", URL]),
            proc(21, "disclaimer", 10, ["disclaimer"]),
            proc(22, "npm exec mcp-re", 21, [f"npm exec mcp-remote@latest {URL}"]),
            proc(23, "node-MainThread", 22, ["node", "mcp-remote", URL]),
            proc(30, "codex", 1, ["codex"]),
            proc(32, "npm exec mcp-re", 30, [f"npm exec mcp-remote@latest {URL}"])]


def test_scan_finds_owner_endpoint_and_status():
    stdin = {12: 100, 22: 200, 32: 300}.get
    peers = {100: {10}, 200: {10}, 300: set()}
    found = {b.pid: b for b in mb.scan(host(), peers=peers, stdin_fn=stdin)}
    assert found[12].client == "claude-desktop" and found[12].client_pid == 10
    assert found[12].endpoint == URL and [m.pid for m in found[12].members] == [12, 13]
    assert found[12].status == found[22].status == mb.DUPLICATE
    assert found[32].status == mb.ORPHAN and found[32].client == "codex"
    assert mb.stoppable(found[12], found.values())[0] and mb.stoppable(found[32], found.values())[0]
    alone = {b.pid: b for b in mb.scan(host()[:4], peers={100: {10}}, stdin_fn=stdin)}
    assert alone[12].status == mb.SINGLE and not mb.stoppable(alone[12], alone.values())[0]
    unknown = mb.scan(host(), peers=None, stdin_fn=stdin)
    assert all(b.connected is None and b.status == mb.UNKNOWN for b in unknown)
    assert not any(mb.stoppable(b, unknown)[0] for b in unknown)  # no evidence, no stop


def test_socket_peers_parses_ss():
    out = ('u_str ESTAB 0 0 * 100 * 101 users:(("npm exec mcp-re",pid=12,fd=0),("node",pid=13,fd=0))\n'
           'u_str ESTAB 0 0 * 101 * 100 users:(("claude-desktop",pid=10,fd=174))\n')
    run = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, out, "")
    peers = mb.socket_peers(run)
    assert peers[100] == {10} and peers[101] == {12, 13}


def children():
    return [subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]) for _ in range(2)]


def bridge_of(child, sibling, *, connected=True, client=1):
    live = procfs.read_proc(Path("/proc"), child.pid)
    return mb.Bridge(child.pid, live.starttime, (live,), URL, client, "cliente", connected, 1, 0.0,
                     mb.DUPLICATE if sibling else mb.SINGLE)


def test_stop_reviewed_duplicate_and_report_health(tmp_path):
    kids = children()
    try:
        target = bridge_of(kids[0], True)
        keep = bridge_of(kids[1], True)
        state = {"bridges": (target, keep)}
        scan = lambda: tuple(b for b in state["bridges"] if kids[[k.pid for k in kids].index(b.pid)].poll() is None)
        plan = actions.plan_for(target, boot_id="b")
        coordinator = Coordinator(journal=Journal(tmp_path / "j"), lock_path=tmp_path / "l")
        verdict = actions.execute(plan, scan=lambda: tuple(
            b if b.pid != keep.pid or kids[0].poll() is None else
            mb.Bridge(**{**b.__dict__, "status": mb.SINGLE}) for b in scan()),
            reaper=Reaper(follow_up_s=3.0), confirm=True, coordinator=coordinator,
            boot_id_fn=lambda: "b", alive_fn=lambda url: True)
        assert verdict.outcome is Outcome.OK, verdict.reason
        assert kids[0].wait(timeout=5) is not None and kids[1].poll() is None
        assert verdict.effects["health"]["connected"] == 1 and "MCP OK" in verdict.reason
    finally:
        for kid in kids:
            kid.kill()


def test_last_connected_bridge_and_changed_identity_are_refused(tmp_path):
    kids = children()
    try:
        never = Reaper(kill_fn=lambda *a: (_ for _ in ()).throw(AssertionError("no signal")))
        only = bridge_of(kids[0], False)
        common = dict(reaper=never, confirm=True, boot_id_fn=lambda: "b", alive_fn=lambda url: True)
        coordinator = Coordinator(journal=Journal(tmp_path / "j1"), lock_path=tmp_path / "l1")
        verdict = actions.execute(actions.plan_for(only, boot_id="b"), scan=lambda: (only,),
                                  coordinator=coordinator, **common)
        assert verdict.outcome is Outcome.REFUSED and "única" in verdict.reason
        dup = bridge_of(kids[0], True)
        moved = mb.Bridge(**{**dup.__dict__, "starttime": dup.starttime + 1})
        coordinator = Coordinator(journal=Journal(tmp_path / "j2"), lock_path=tmp_path / "l2")
        verdict = actions.execute(actions.plan_for(dup, boot_id="b"), scan=lambda: (moved, bridge_of(kids[1], True)),
                                  coordinator=coordinator, **common)
        assert verdict.outcome is Outcome.REFUSED and "identidade" in verdict.reason
        assert all(k.poll() is None for k in kids)
    finally:
        for kid in kids:
            kid.kill()
