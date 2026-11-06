import configparser

import pytest

from folego.ui.screen_energy import ScreenEnergy, ScreenEnergyError, PROFILES


def fake_plasma(path):
    calls = []
    def run(argv):
        calls.append(argv)
        if argv[0] == 'kwriteconfig6':
            parser = configparser.RawConfigParser(interpolation=None)
            parser.optionxform = str
            if path.exists(): parser.read(path)
            section = argv[argv.index('--group') + 1] + '][Display'
            if not parser.has_section(section): parser.add_section(section)
            key = argv[argv.index('--key') + 1]
            if '--delete' in argv:
                parser.remove_option(section, key)
            else:
                parser.set(section, key, argv[-1])
            with path.open('w') as output: parser.write(output)
        return 'a(ssssu) 0' if argv[0] == 'busctl' else ''
    return run, calls


def test_plasma_timeout_is_opt_in_reversible_and_pauses_for_dock(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'KDE')
    monkeypatch.setattr('folego.ui.screen_energy.shutil.which', lambda _: '/fixture/tool')
    config = tmp_path / 'powerdevilrc'
    config.write_text('[AC][Display]\nTurnOffDisplayWhenIdle=false\n')
    receipt = tmp_path / 'receipt.json'
    run, calls = fake_plasma(config)
    dock = [False]
    screen = ScreenEnergy(config=config, receipt=receipt, command=run,
                          topology=lambda: 'dock' if dock[0] else 'portátil',
                          fullscreen=lambda: False)
    assert not screen.status()['enabled']
    assert screen.enable()['active']
    assert receipt.exists()
    assert all(screen.status()['enabled'] for _ in range(2))
    dock[0] = True
    assert not screen.reconcile()['active']
    dock[0] = False
    assert screen.reconcile()['active']
    assert screen.disable()['enabled'] is False
    assert not receipt.exists()
    assert screen_energy_settings(config)['AC']['TurnOffDisplayWhenIdle'] == 'false'
    assert all('TurnOffDisplayIdleTimeoutSec' not in config.read_text()
               for _ in PROFILES)
    assert any(argv[0] == 'qdbus6' for argv in calls)


def screen_energy_settings(path):
    from folego.ui.screen_energy import _settings
    return _settings(path)


def test_external_change_is_preserved_and_blocks_restore(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'KDE')
    monkeypatch.setattr('folego.ui.screen_energy.shutil.which', lambda _: '/fixture/tool')
    config = tmp_path / 'powerdevilrc'
    run, _ = fake_plasma(config)
    screen = ScreenEnergy(config=config, receipt=tmp_path / 'receipt.json',
                          command=run, topology=lambda: 'portátil', fullscreen=lambda: False)
    screen.enable()
    config.write_text(config.read_text().replace('180', '300'))
    assert screen.status()['unknown']
    with pytest.raises(ScreenEnergyError, match='outro owner'):
        screen.disable()
    assert '300' in config.read_text()


def test_dock_disables_only_internal_after_external_is_active_and_recovers(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'KDE')
    monkeypatch.setattr('folego.ui.screen_energy.shutil.which', lambda _: '/fixture/tool')
    config = tmp_path / 'powerdevilrc'
    run, calls = fake_plasma(config)
    physical = {'external': True, 'internal': True}
    def topology():
        return {'mode': 'dock' if physical['external'] else 'portátil',
                'internal': 'eDP-1', 'internal_enabled': physical['internal'],
                'external_active': physical['external']}
    def command(argv):
        if argv[0] == 'kscreen-doctor':
            physical['internal'] = argv[1].endswith('.enable')
            calls.append(argv)
            return ''
        return run(argv)
    screen = ScreenEnergy(config=config, receipt=tmp_path / 'receipt.json',
                          command=command, topology=topology, fullscreen=lambda: False)
    assert 'Dock ativo' in screen.enable()['message']
    assert not physical['internal'] and physical['external']
    physical['external'] = False
    assert screen.reconcile()['active']
    assert physical['internal']
    assert [argv[1] for argv in calls if argv[0] == 'kscreen-doctor'] == [
        'output.eDP-1.disable', 'output.eDP-1.enable']
    screen.disable()


def test_unknown_window_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'KDE')
    monkeypatch.setattr('folego.ui.screen_energy.shutil.which', lambda _: '/fixture/tool')
    config = tmp_path / 'powerdevilrc'
    run, _ = fake_plasma(config)
    screen = ScreenEnergy(config=config, receipt=tmp_path / 'receipt.json',
                          command=run, topology=lambda: 'portátil',
                          fullscreen=lambda: (_ for _ in ()).throw(ScreenEnergyError('unknown')))
    assert screen.enable()['active'] is False
    assert screen.disable()['enabled'] is False


def test_option_displays_blocked_state_and_emits_request(qapp):
    from folego.ui.options_tab import OptionsTab
    tab = OptionsTab()
    tab.build_desktop_options()
    requests = []
    tab.screen_energy_requested.connect(requests.append)
    tab.show_screen_energy({'enabled': False, 'message': 'Desligada'})
    tab.screen_energy_choice.click()
    assert requests == ['enable']
    tab.show_screen_energy({'enabled': True, 'blocked': True,
                            'message': 'Plasma mantém a tela acesa'})
    assert tab.screen_energy_choice.isChecked()
    assert 'Plasma' in tab.screen_energy_status.text()


def test_hotplug_reconciles_immediately_and_idle_probe_is_bounded(qapp):
    from folego.ui.main_window import MainWindow
    window = MainWindow(collector_factory=None, startup_defaults=False)
    try:
        window.options.show_screen_energy({'enabled': True, 'message': 'Ligada'})
        calls = []
        window._screen_controller.request = lambda action, value=None: calls.append(action) or True
        window._screen_change()
        window._screen_energy_tick()
        window._screen_tick_count = 5
        window._screen_energy_tick()
        assert calls == ['reconcile', 'attention', 'reconcile']
    finally:
        window.close()
