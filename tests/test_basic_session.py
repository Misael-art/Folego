"""Login changes only touch disposable configuration; never contact systemd."""
import json
import os
from pathlib import Path

import pytest

from folego import basic_session, startup, cli
from folego.basic_session import BasicSession, BasicSessionError, DESKTOPS, UNITS


@pytest.fixture
def manager(fake_home, monkeypatch):
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'KDE')
    config = fake_home / '.config'
    system = fake_home / 'system-xdg'
    units = fake_home / 'vendor-units'
    (system / 'autostart').mkdir(parents=True)
    units.mkdir()
    for name in ('powerdevil.desktop', 'kaccess.desktop', 'big-preload-user.desktop'):
        (system / 'autostart' / name).write_text('[Desktop Entry]\nType=Application\nExec=/bin/true\n')
    (units / 'hermes-gateway.service').write_text('[Service]\nExecStart=/bin/true\n')
    return BasicSession(config=config, system_config=[system], unit_dirs=[units])


def add_personal(manager, name='steam-input.desktop'):
    path = manager.config / 'autostart' / name
    path.parent.mkdir(exist_ok=True)
    original = b'# personal comment\n[Desktop Entry]\nType=Application\nName=Steam\nExec=steam -silent\nHidden=false\n'
    path.write_bytes(original)
    path.chmod(0o640)
    return path, original


def test_default_on_is_read_only_then_preserves_core_and_restores_exact_bytes(manager):
    personal, original = add_personal(manager)
    assert startup.preference()['basic_session'] is True
    assert manager.status()['state'] == 'unconfigured'
    assert not manager.state.exists()
    applied = manager.configure()
    assert applied['configured'] and applied['operation_id']
    assert personal.read_bytes().startswith(b'# personal comment')
    assert 'Hidden=true' in personal.read_text()
    assert not (manager.config / 'autostart/powerdevil.desktop').exists()
    assert not (manager.config / 'autostart/kaccess.desktop').exists()
    assert os.readlink(manager.config / 'systemd/user/hermes-gateway.service') == '/dev/null'
    assert (manager.config / 'ksmserverrc').read_text() == '[General]\nloginMode=emptySession\n'
    assert manager.state.stat().st_mode & 0o077 == 0
    restored = manager.configure(False)
    assert restored['state'] == 'restored' and not restored['enabled']
    assert personal.read_bytes() == original and personal.stat().st_mode & 0o777 == 0o640
    assert not (manager.config / 'autostart/big-preload-user.desktop').exists()
    assert not (manager.config / 'ksmserverrc').exists()
    assert not (manager.config / 'systemd/user/hermes-gateway.service').is_symlink()
    assert startup.preference()['enabled'] is True  # Independent Fôlego autostart choice.


def test_original_unit_symlink_and_disabled_desktop_remain_owned_by_user(manager):
    unit = manager.config / 'systemd/user/hermes-gateway.service'
    unit.parent.mkdir(parents=True)
    unit.symlink_to('/a/personal/unit.service')
    desktop, _ = add_personal(manager)
    desktop.write_text('[Desktop Entry]\nHidden=true\n')
    manager.configure()
    manager.configure(False)
    assert os.readlink(unit) == '/a/personal/unit.service'
    assert desktop.read_text() == '[Desktop Entry]\nHidden=true\n'


def test_external_edits_block_restoration_and_automatic_sync(manager):
    personal, _ = add_personal(manager)
    manager.configure()
    personal.write_text('[Desktop Entry]\nHidden=false\nExec=new-choice\n')
    before = personal.read_bytes()
    assert manager.status()['state'] == 'conflict'
    with pytest.raises(BasicSessionError, match='externa'):
        manager.configure(False)
    with pytest.raises(BasicSessionError, match='externa'):
        manager.configure()
    assert personal.read_bytes() == before


def test_interrupted_intent_never_retries_and_explicit_restore_recovers_partial(manager, monkeypatch):
    personal, original = add_personal(manager)
    real = manager._write
    calls = []
    def fail_after_first(target, desired, expected):
        calls.append(target)
        if len(calls) == 2: raise OSError('interrupted')
        real(target, desired, expected)
    monkeypatch.setattr(manager, '_write', fail_after_first)
    result = manager.configure()
    assert result['outcome'] == 'desconhecido'
    assert manager.configure()['outcome'] == 'desconhecido'
    assert len(calls) == 2  # No replay.
    assert manager.configure(reconcile=True)['outcome'] == 'desconhecido'
    monkeypatch.setattr(manager, '_write', real)
    assert manager.configure(False)['state'] == 'restored'
    assert personal.read_bytes() == original


def test_read_only_reconcile_confirms_completed_effect_without_rewriting(manager, monkeypatch):
    manager.configure()
    row = json.loads(manager.state.read_text()); row['phase'] = 'intended'
    manager.state.write_text(json.dumps(row))
    monkeypatch.setattr(manager, '_write', lambda *_: pytest.fail('replay'))
    result = manager.configure(reconcile=True)
    assert result['configured'] and result['operation_id'] == row['operation_id']


def test_unknown_launcher_is_preserved_and_not_reported_as_suppressed(manager):
    unknown, original = add_personal(manager, 'unknown-owner.desktop')
    result = manager.configure()
    assert result['preserved'] == ['unknown-owner.desktop']
    assert unknown.read_bytes() == original
    assert unknown.name not in result['targets']


def test_symlink_or_unreadable_configuration_fails_before_any_target_effect(manager):
    personal, _ = add_personal(manager)
    personal.unlink(); personal.symlink_to(manager.config / 'missing')
    with pytest.raises(BasicSessionError): manager.configure()
    assert not manager.state.exists()
    assert not (manager.config / 'ksmserverrc').exists()


def test_receipt_cannot_redirect_restoration_outside_catalog(manager):
    manager.configure()
    row = json.loads(manager.state.read_text())
    row['entries'][0]['path'] = str(manager.config / 'credentials')
    manager.state.write_text(json.dumps(row))
    with pytest.raises(BasicSessionError, match='Escopo'): manager.configure(False)


def test_damaged_original_in_receipt_cannot_be_restored(manager):
    import base64
    add_personal(manager); manager.configure()
    row = json.loads(manager.state.read_text())
    entry = next(e for e in row['entries'] if e['before']['kind'] == 'file')
    entry['before']['data'] = base64.b64encode(b'corrupted original').decode()
    manager.state.write_text(json.dumps(row))
    with pytest.raises(BasicSessionError, match='hash'): manager.configure(False)


def test_session_preferences_preserve_other_groups_and_missing_newline(manager):
    path = manager.config / 'ksmserverrc'
    original = b'[General]\nloginMode=restorePreviousLogout\nconfirmLogout=true\n[Other]\nvalue=exact'
    path.write_bytes(original)
    manager.configure()
    assert 'loginMode=emptySession' in path.read_text() and path.read_bytes().endswith(b'value=exact')
    manager.configure(False)
    assert path.read_bytes() == original


def test_new_recognized_app_extends_receipt_without_losing_originals(manager):
    path, original = add_personal(manager)
    first = manager.configure()['operation_id']
    new, new_original = add_personal(manager, 'discord.desktop')
    second = manager.configure()['operation_id']
    assert first != second
    manager.configure(False)
    assert path.read_bytes() == original and new.read_bytes() == new_original


def test_non_kde_and_unknown_preference_are_preserved(manager, monkeypatch):
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'GNOME')
    with pytest.raises(BasicSessionError, match='KDE'): manager.configure()
    startup.save_object(startup.paths.config_dir() / 'startup.json',
                        {'schema': 1, 'enabled': True, 'basic_session': 'yes'})
    with pytest.raises(ValueError, match='desconhecida'): manager.status()


def test_catalog_never_targets_core_services_or_folego():
    assert not any(name.startswith(('folego-', 'plasma-kwin', 'pipewire', 'wireplumber',
                                    'dbus', 'plasma-powerdevil')) for name in UNITS)
    assert 'folego.desktop' not in DESKTOPS


@pytest.mark.parametrize('raw', (b'[General][$i]\nloginMode=restorePreviousLogout\n',
                               b'[General]\nloginMode[$i]=restorePreviousLogout\n'))
def test_immutable_plasma_preferences_block_whole_plan(manager, raw):
    path = manager.config / 'ksmserverrc'; path.write_bytes(raw)
    with pytest.raises(BasicSessionError, match='imut'): manager.configure()
    assert path.read_bytes() == raw and not manager.state.exists()


def test_cli_requires_confirmation_and_returns_native_status(manager, monkeypatch, capsys):
    monkeypatch.setattr(basic_session, 'BasicSession', lambda: manager)
    assert cli.main(['startup', 'basic-enable', '--json']) != 0
    assert not manager.state.exists()
    capsys.readouterr()
    assert cli.main(['startup', 'basic-status', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['default_enabled'] is True
    assert cli.main(['startup', 'basic-enable', '--confirmar', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['configured']
