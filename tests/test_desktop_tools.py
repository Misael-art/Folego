import subprocess

import pytest

from folego.adapters.desktop_tools import DesktopTools


def test_shortcuts_send_only_the_explicit_combo_and_never_replay(monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")
    monkeypatch.setattr("folego.adapters.desktop_tools.shutil.which", lambda name: "/bin/" + name)
    tool = DesktopTools(env={"DISPLAY": ":private", "XDG_SESSION_TYPE": "x11"}, run=run)
    tool.perform("copy")
    tool.perform("paste")
    assert [call[-1] for call in calls] == ["ctrl+Insert", "shift+Insert"]
    assert all(call[-1] != "ctrl+c" for call in calls), "copy must not interrupt a terminal job"
    assert all("--clearmodifiers" not in call for call in calls)
    calls.clear()
    tool.run = lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("input", 5))
    with pytest.raises(subprocess.TimeoutExpired): tool.perform("copy")
    assert not calls


@pytest.mark.parametrize("codes", [[], [0], [128], [True], [30] * 9])
def test_invalid_key_combinations_refuse_before_backend(codes):
    with pytest.raises(ValueError): DesktopTools(env={}).keys(codes)


def test_close_never_signals_an_unowned_daemon():
    class Child:
        terminated = False
        def poll(self): return 0
        def terminate(self): self.terminated = True
    child = Child()
    tool = DesktopTools(env={})
    tool.daemon = child
    assert tool.close()
    assert not child.terminated and tool.daemon is None


def test_unknown_action_is_refused():
    with pytest.raises(ValueError): DesktopTools(env={}).perform("reset-input")


def test_widget_place_requires_unique_owned_window_and_confirmed_geometry(monkeypatch):
    tool = DesktopTools(env={})
    calls = []
    geometry = (12, 34, 220, 600)
    def read(argv):
        calls.append(argv)
        if argv[:2] == ['kdotool', 'search']:
            return 'owned-window'
        if argv[:2] == ['kdotool', 'getwindowgeometry']:
            return 'Position: 12,34 Geometry: 220x600'
        raise AssertionError(argv)
    monkeypatch.setattr(tool, '_call', read)
    monkeypatch.setattr(tool, 'position', lambda caption, requested, confirmation=None:
                        confirmation.wait(.1) or (_ for _ in ()).throw(AssertionError('not confirmed')))
    assert tool.perform('widget-geometry') == {'operation': 'widget-geometry', 'geometry': geometry}
    assert tool.perform('widget-place', geometry) == {'operation': 'widget-place', 'geometry': geometry}
    assert any('--pid' in argv and '^Fôlego — widget$' in argv for argv in calls)
    monkeypatch.setattr(tool, '_call', lambda argv: 'other-window\nowned-window'
                        if argv[:2] == ['kdotool', 'search'] else read(argv))
    with pytest.raises(RuntimeError, match='não identificada'):
        tool.perform('widget-geometry')
    with pytest.raises(AssertionError, match='not confirmed'):
        tool.perform('widget-place', geometry)
