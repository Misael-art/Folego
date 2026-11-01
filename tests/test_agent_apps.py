import subprocess

import pytest

from folego.adapters.agent_apps import AgentApps

WINDOW = '{00000000-0000-0000-0000-000000000001}'


class Monitor:
    def __init__(self): self.seen = []
    def acknowledge(self, pending): self.seen.extend(pending)


def test_open_confirms_focus_before_acknowledging(monkeypatch):
    calls = []
    view = Monitor()
    def run(argv, **kwargs):
        calls.append(argv)
        output = '123' if argv[1] == 'getwindowpid' else WINDOW if argv[1] in ('search', 'getactivewindow') else ''
        if argv[1] == 'windowactivate': assert not view.seen
        return subprocess.CompletedProcess(argv, 0, output, '')
    monkeypatch.setattr('folego.adapters.agent_apps.shutil.which', lambda _: '/bin/kdotool')
    monkeypatch.setattr('folego.adapters.agent_apps.identity', lambda pid: (pid, 1, 100))
    apps = AgentApps(view, env={'XDG_SESSION_TYPE': 'wayland'}, run=run, discover=lambda: [])
    apps.perform('agent-open', ('codex', [{'event': 'snapshot'}]))
    assert view.seen == [{'event': 'snapshot'}]
    assert [a[1] for a in calls].count('windowactivate') == 1
    assert not any(a[1] in ('windowclose', 'key', 'type') for a in calls)


def test_changed_owner_refuses_activation_and_preserves_badge(monkeypatch):
    monitor = Monitor()
    calls = []
    pids = iter(['123', '124'])
    def run(argv, **kwargs):
        calls.append(argv)
        output = next(pids) if argv[1] == 'getwindowpid' else WINDOW
        return subprocess.CompletedProcess(argv, 0, output, '')
    monkeypatch.setattr('folego.adapters.agent_apps.shutil.which', lambda _: '/bin/kdotool')
    monkeypatch.setattr('folego.adapters.agent_apps.identity', lambda pid: (pid, 1, 100))
    apps = AgentApps(monitor, env={'XDG_SESSION_TYPE': 'wayland'}, run=run, discover=lambda: [])
    with pytest.raises(RuntimeError): apps.perform('agent-open', ('codex', [{'event': 'snapshot'}]))
    assert not monitor.seen and not any(a[1] == 'windowactivate' for a in calls)


def test_missing_window_or_launcher_never_clears_notices(monkeypatch):
    monitor = Monitor()
    monkeypatch.setattr('folego.adapters.agent_apps.shutil.which', lambda n: '/bin/kdotool' if n == 'kdotool' else None)
    apps = AgentApps(monitor, env={'XDG_SESSION_TYPE': 'wayland'},
                     run=lambda a, **k: subprocess.CompletedProcess(a, 0, '', ''), discover=lambda: [])
    with pytest.raises(RuntimeError): apps.perform('agent-open', ('grok', [{'event': 'snapshot'}]))
    assert not monitor.seen


def test_cli_window_requires_live_ancestry_and_terminal_class(monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        output = WINDOW if '--pid' in argv and argv[argv.index('--pid') + 1] == '20' else ''
        return subprocess.CompletedProcess(argv, 0, output, '')
    identities = {30: (30, 20, 1), 20: (20, 10, 2), 10: (10, 1, 3)}
    monkeypatch.setattr('folego.adapters.agent_apps.identity', identities.get)
    processes = [dict(provider='grok', pid=30, identity=identities[30], roots={}, server=False)]
    apps = AgentApps(Monitor(), env={'XDG_SESSION_TYPE': 'wayland'}, run=run, discover=lambda: processes)
    assert apps._windows('/bin/kdotool', 'grok') == [WINDOW]
    assert all('--all' in c and '--class' in c for c in calls if '--pid' in c)
    processes[0]['identity'] = (30, 20, 99)
    assert apps._windows('/bin/kdotool', 'grok') == []
