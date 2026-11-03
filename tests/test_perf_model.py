from folego.core import agents, perf_model
from folego.core.snapshot import MemInfo, ProcInfo, Snapshot

APP = "/user.slice/user-1000.slice/user@1000.service/app.slice/"


def proc(pid, comm, ppid=1, rss=100_000, cpu=1.0, exe=None):
    return ProcInfo(pid, comm, "S", ppid, pid, pid, 0, 0, pid, rss, 0, 1000,
                    (exe or "/usr/bin/" + comm,), cpu_frac=cpu)


def host(tmp_path):
    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)
    procs = [
        proc(10, "claude-desktop", exe="/x/claude-desktop/app"), proc(11, "node", ppid=10),
        proc(20, "konsole"), proc(21, "bash", ppid=20), proc(22, "pytest", ppid=21, cpu=200.0),
        proc(30, "msedge", rss=2_000_000), proc(31, "msedge", ppid=30, cpu=None),
        proc(40, "plasmashell"), proc(50, "folego"), proc(60, "weird"),
    ]
    units = {10: "app-com.anthropic.Claude-10.scope", 11: "app-com.anthropic.Claude-10.scope",
             20: "app-org.kde.konsole-20.scope", 21: "app-org.kde.konsole-20.scope",
             22: "app-org.kde.konsole-20.scope", 30: "app-microsoft\\x2dedge@ab12cd34ef.service",
             31: "app-microsoft\\x2dedge@ab12cd34ef.service",
             40: "plasma-plasmashell.service", 50: "app-folego@autostart.service"}
    cwds = {22: str(project / "src"), 21: "/home"}
    return procs, units, cwds, project


def test_agent_trees_and_projects_are_protected(tmp_path):
    procs, _, cwds, project = host(tmp_path)
    act = agents.detect(procs, cwd_fn=cwds.get)
    assert {10, 11, 20, 21, 22} <= act.protected  # ancestry of project work included
    assert 30 not in act.protected and 31 not in act.protected
    assert act.projects == {str(project)} and act.load == agents.BUSY


def test_groups_only_observe_plain_apps(tmp_path):
    procs, units, cwds, _ = host(tmp_path)
    snap = Snapshot(0.0, MemInfo(16_000_000, 6_000_000), 0, 0, None, None, None, None, (), 0,
                    procs=tuple(procs))
    view = perf_model.build(snap, agents.detect(procs, cwd_fn=cwds.get),
                            cgroup_fn=lambda pid: APP + units[pid] if pid in units else None)
    by = {g.label: g for g in view.groups}
    assert by["microsoft-edge"].state == perf_model.OBSERVED
    assert by["microsoft-edge"].cpu_frac == 1.0  # a new member has no delta yet
    assert by["com.anthropic.Claude"].state == perf_model.AGENT
    assert by["org.kde.konsole"].state == perf_model.AGENT
    assert by["plasma-plasmashell"].state == perf_model.PROTECTED
    assert by["folego"].state == perf_model.PROTECTED
    assert by["?"].state == perf_model.PROTECTED  # unidentified never becomes a candidate
    assert view.reclaimable_kb() == 2_100_000


def test_unreadable_cwd_and_unmeasured_cpu_stay_protective(tmp_path):
    procs = [proc(1_0, "claude", cpu=None)]
    act = agents.detect(procs, cwd_fn=lambda pid: None)
    assert act.load == agents.INTERACTIVE and act.cpu_frac is None
