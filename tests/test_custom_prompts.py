import copy
import json
import os
import subprocess

import pytest

from folego.core.custom_prompts import CustomPrompts, DEFAULTS, shortcut_codes
from folego.adapters.desktop_tools import DesktopTools


def test_missing_library_has_literal_123_without_creating_file(tmp_path):
    path = tmp_path / 'custom.json'
    value = CustomPrompts(path).read()
    assert value['entries'][0]['text'] == value['entries'][0]['title'] == '123'
    assert value['entries'][1]['action'] == 'desktop'
    assert not path.exists()


def test_roundtrip_whitespace_private_permissions_and_explicit_empty(tmp_path):
    store = CustomPrompts(tmp_path / 'custom.json')
    data = store.read()
    data['entries'][0]['text'] = '  123\nTexto com acentos\n'
    saved = store.save(data['entries'], data['revision'])
    assert saved['entries'][0]['text'] == data['entries'][0]['text']
    assert os.stat(store.path).st_mode & 0o777 == 0o600
    store.save([], saved['revision'])
    assert CustomPrompts(store.path).read()['entries'] == []


@pytest.mark.parametrize('value', [{'schema': 99, 'entries': []}, {'schema': True, 'entries': []},
                                  {'schema': 1, 'entries': [], 'future': True}, {'bad': 'secret'}])
def test_unknown_configuration_never_becomes_defaults_or_is_overwritten(tmp_path, value):
    path = tmp_path / 'custom.json'
    raw = json.dumps(value).encode(); path.write_bytes(raw)
    store = CustomPrompts(path)
    with pytest.raises(ValueError): store.read()
    with pytest.raises(ValueError): store.save(DEFAULTS, 'missing')
    assert path.read_bytes() == raw


def test_stale_editor_or_menu_cannot_overwrite_or_invoke_changed_item(tmp_path):
    store = CustomPrompts(tmp_path / 'custom.json')
    first = store.read(); saved = store.save(first['entries'], first['revision'])
    changed = copy.deepcopy(saved['entries']); changed[1]['action'] = 'keys'; changed[1]['shortcut'] = 'Meta+D'
    store.save(changed, saved['revision']); before = store.path.read_bytes()
    with pytest.raises(ValueError, match='outra janela'): store.save(first['entries'], saved['revision'])
    with pytest.raises(ValueError, match='alterado'): store.resolve(changed[1]['id'], saved['revision'])
    assert store.path.read_bytes() == before


def test_symlink_and_fifo_sources_are_not_followed_or_blocking(tmp_path):
    target = tmp_path / 'target'; target.write_text('private')
    path = tmp_path / 'custom.json'; path.symlink_to(target)
    with pytest.raises(ValueError): CustomPrompts(path).read()
    assert target.read_text() == 'private'
    fifo = tmp_path / 'fifo'; os.mkfifo(fifo)
    with pytest.raises(ValueError): CustomPrompts(fifo).read()


@pytest.mark.parametrize('shortcut,codes', [('Meta+D', [125, 32]), ('Ctrl+Alt+T', [29, 56, 20]),
    ('Ctrl+Shift+F12', [29, 42, 88]), ('Alt+Tab', [56, 15])])
def test_shortcuts_have_one_explicit_key_chord(shortcut, codes):
    assert shortcut_codes(shortcut) == codes


@pytest.mark.parametrize('shortcut', ['', 'Ctrl+Ctrl+A', 'Ctrl+K, Ctrl+C', 'rm -rf /', 'Ctrl+NotAKey'])
def test_commands_or_invalid_chords_are_not_keyboard_macros(shortcut):
    with pytest.raises(ValueError): shortcut_codes(shortcut)


def test_copy_resolution_never_sends_input_or_desktop_effect(tmp_path, monkeypatch):
    backend = DesktopTools(env=dict(HOME=str(tmp_path)))
    monkeypatch.setattr(backend, 'keys', lambda *_: pytest.fail('copy sent keyboard input'))
    monkeypatch.setattr(backend, 'show_desktop', lambda: pytest.fail('copy invoked desktop macro'))
    loaded = backend.perform('custom-load')
    result = backend.perform('custom-use', dict(id='example-text', revision=loaded['revision']))
    assert result == dict(operation='custom-copy', text='123')


def test_desktop_macro_requests_show_once_and_verifies_state(monkeypatch):
    monkeypatch.setattr('folego.adapters.desktop_tools.shutil.which', lambda _: 'qdbus6')
    calls, showing = [], [False]
    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b'true' if showing[0] else b'false', b'')
    effects = []
    def show():
        effects.append(True)
        showing[0] = True
    backend = DesktopTools(run=run, desktop_show=show)
    assert backend.show_desktop() == 'Área de trabalho exibida'
    assert effects == [True]
    assert backend.show_desktop() == 'A área de trabalho já está visível'
    assert effects == [True]


def test_unknown_desktop_state_refuses_the_effect(monkeypatch):
    monkeypatch.setattr('folego.adapters.desktop_tools.shutil.which', lambda _: 'qdbus6')
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b'unknown', b'')
    with pytest.raises(RuntimeError): DesktopTools(run=run).show_desktop()
    assert not any('org.kde.KWin.showDesktop' in a for a in calls)
