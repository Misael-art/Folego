import json

import pytest

from folego import plasma_widgets as widgets
from folego.basic_session import BasicSession


LAYOUT = b"""[Containments][1]
plugin=org.kde.panel

[Containments][1][Applets][2]
plugin=org.phasezero.deckpanel

[Containments][1][Applets][2][Configuration][General]
detail=keep the widget settings

[Containments][1][Applets][3]
plugin=org.kde.plasma.networkmanagement

[Containments][1][Applets][4]
plugin=org.kde.plasma.systemtray

[Containments][1][Applets][4][Applets][7]
plugin=org.biglinux.micnoise

[Containments][1][Applets][4][General]
extraItems=org.biglinux.micnoise,org.kde.plasma.volume
knownItems=org.biglinux.micnoise,org.kde.plasma.volume

[Containments][1][General]
AppletOrder=3;2;4
"""


def test_disables_only_catalogued_widgets_and_restores_the_original_bytes():
    reduced, names = widgets.disable_layout(LAYOUT)
    assert names == ['org.biglinux.micnoise', 'org.phasezero.deckpanel']
    assert b'[Applets][2]' not in reduced and b'[Applets][7]' not in reduced
    assert b'AppletOrder=3;4' in reduced
    assert b'extraItems=org.kde.plasma.volume' in reduced
    assert b'knownItems=org.biglinux.micnoise,org.kde.plasma.volume' in reduced
    assert b'plugin=org.kde.plasma.networkmanagement' in reduced
    assert b'plugin=org.kde.plasma.systemtray' in reduced
    assert widgets.restore_layout(reduced, LAYOUT) == LAYOUT


def test_restores_widget_settings_and_preserves_later_edits():
    reduced, _ = widgets.disable_layout(LAYOUT)
    changed = reduced.replace(b'AppletOrder=3;4', b'AppletOrder=3;9;4')
    changed = changed.replace(b'extraItems=org.kde.plasma.volume',
                              b'extraItems=org.kde.plasma.volume,org.kde.plasma.clipboard')
    restored = widgets.restore_layout(changed, LAYOUT)
    assert b'AppletOrder=3;9;2;4' in restored
    assert b'extraItems=org.biglinux.micnoise,org.kde.plasma.volume,org.kde.plasma.clipboard' in restored
    assert b'detail=keep the widget settings' in restored
    with pytest.raises(ValueError, match='reutilizada'):
        widgets.restore_layout(changed + b'[Containments][1][Applets][2]\nplugin=other\n', LAYOUT)


def test_unknown_tray_registry_leaves_the_layout_protected():
    raw = LAYOUT.replace(b'knownItems=org.biglinux.micnoise,', b'knownItems=')
    with pytest.raises(ValueError, match='bandeja'):
        widgets.disable_layout(raw)


def test_basic_session_schedules_drop_in_and_prepares_and_restores_only_before_plasma(tmp_path, monkeypatch):
    config = tmp_path / 'config'
    state = tmp_path / 'state'
    units = tmp_path / 'units'
    config.mkdir()
    units.mkdir()
    (units / widgets.UNIT).write_text('[Service]\nExecStart=/usr/bin/plasmashell\n')
    layout = config / widgets.LAYOUT
    layout.write_bytes(LAYOUT)
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'KDE')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config))
    monkeypatch.setenv('XDG_STATE_HOME', str(state))
    reloads = []
    original = widgets.ensure_hook

    def plan(*args):
        return original(*args, reload=lambda: reloads.append(True))

    monkeypatch.setattr(widgets, 'ensure_hook', plan)
    manager = BasicSession(config=config, state=state / 'basic-session.json',
                           system_config=(), unit_dirs=(units,))
    assert manager.configure(True)['widgets']['state'] == 'scheduled'
    assert len(reloads) == 1
    assert b'ExecStartPre=-' in (config / widgets.HOOK).read_bytes()
    assert layout.read_bytes() == LAYOUT
    with pytest.raises(ValueError, match='fora de execução'):
        widgets.prepare(config=config, state=state / 'basic-widgets.json', before_plasma=lambda: False)
    def prepare():
        return widgets.prepare(config=config, state=state / 'basic-widgets.json', before_plasma=lambda: True)

    assert prepare()['state'] == 'applied'
    assert b'plugin=org.phasezero.deckpanel' not in layout.read_bytes()
    assert manager.status()['widgets']['state'] == 'applied'
    assert manager.configure(False)['widgets']['state'] == 'scheduled'
    assert b'plugin=org.phasezero.deckpanel' not in layout.read_bytes()
    assert prepare()['state'] == 'restored'
    assert layout.read_bytes() == LAYOUT


def test_interrupted_layout_write_blocks_replay(tmp_path, monkeypatch):
    layout = tmp_path / widgets.LAYOUT
    state = tmp_path / 'basic-widgets.json'
    layout.write_bytes(LAYOUT)
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path))
    def prepare():
        return widgets.prepare(config=tmp_path, state=state, enabled=True, before_plasma=lambda: True)
    def interrupted(*args, **kwargs):
        raise OSError('interrupção simulada')

    monkeypatch.setattr(widgets, 'write_atomic', interrupted)
    with pytest.raises(OSError, match='interrupção simulada'):
        prepare()
    previous = json.loads(state.read_bytes())
    assert previous['phase'] == 'intended'
    assert layout.read_bytes() == LAYOUT
    with pytest.raises(ValueError, match=previous['operation_id']):
        prepare()
    assert previous == json.loads(state.read_bytes())
