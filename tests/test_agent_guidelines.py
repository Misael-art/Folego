"""Instruction effects are confined to the private HOME of each test."""
import base64
import hashlib
import json
from pathlib import Path

import pytest

from folego import cli
from folego.actions import agent_guidelines as care


@pytest.fixture
def manager(fake_home):
    for relative in ('.codex', '.claude', '.config/opencode', '.gemini', '.hermes',
                     '.cursor', '.continue', '.prime/agent', '.zcode', '.qoder',
                     '.config/Code/User', '.local/share/phasezero/chatgpt-web/codex-home',
                     '.local/share/phasezero/codex/test-profile/native'):
        (fake_home / relative).mkdir(parents=True, exist_ok=True)
    return care.AgentGuidelines()


def personal(manager):
    path = manager.home / '.codex/AGENTS.md'
    original = '# Regras pessoais\r\n\r\n@RTK.md\r\n'.encode()
    path.write_bytes(original)
    path.chmod(0o640)
    return path, original


def test_default_off_and_readonly_discovery(manager):
    before = set(manager.home.rglob('*'))
    result = manager.status()
    assert not result['enabled'] and result['state'] == 'unconfigured'
    assert result['discovered'] == 14
    assert set(manager.home.rglob('*')) == before
    manager.configure()
    assert not manager.state.exists() and not manager.config.exists()


def test_enable_once_and_restore_exact_originals_in_all_clients(manager):
    target, original = personal(manager)
    before = {p: p.read_bytes() for p in manager.home.rglob('*') if p.is_file()}
    result = manager.configure(True)
    assert result['managed'] == 14 and result['enabled'] and result['ok']
    assert target.read_bytes().startswith(original)
    assert target.read_bytes().count(care.BLOCK) == 1
    assert target.stat().st_mode & 0o777 == 0o640
    first = manager.state.read_bytes()
    times = {p: p.stat().st_mtime_ns for p in manager.home.rglob('*') if p.is_file()}
    assert manager.configure()['operation_id'] == result['operation_id']
    assert manager.state.read_bytes() == first
    assert all(p.stat().st_mtime_ns == stamp for p, stamp in times.items())
    restored = manager.configure(False)
    assert not restored['enabled'] and restored['state'] == 'restored'
    assert target.read_bytes() == original and target.stat().st_mode & 0o777 == 0o640
    for name in manager._catalog():
        path = Path(name)
        if path in before:
            assert path.read_bytes() == before[path]
        else:
            assert not path.exists()
    assert manager.state.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize('edit', ['append', 'prepend', 'mode', 'frontmatter'])
def test_restore_removes_only_our_fragment_and_preserves_later_edits(manager, edit):
    target, original = personal(manager)
    if edit == 'frontmatter':
        target = manager.home / '.cursor/rules/host-care.mdc'
    manager.configure(True)
    if edit == 'append':
        target.write_bytes(target.read_bytes() + b'\n# Nova regra pessoal\n')
        expected = original + b'\n# Nova regra pessoal\n'
    elif edit == 'prepend':
        target.write_bytes(b'# Nova regra pessoal\n' + target.read_bytes())
        expected = b'# Nova regra pessoal\n' + original
    elif edit == 'mode':
        target.chmod(0o600)
        expected = original
    else:
        target.write_bytes(target.read_bytes().replace(b'description:', b'name: Meu nome\ndescription:', 1))
        expected = target.read_bytes().replace(care.BLOCK, b'')
    assert manager.configure(False)['ok']
    assert target.read_bytes() == expected
    if edit == 'mode':
        assert target.stat().st_mode & 0o777 == 0o600


def test_new_profile_discovered_while_enabled_and_no_new_file_when_disabled(manager):
    manager.configure(True)
    new = manager.home / '.local/share/phasezero/codex/new-profile/native'
    new.mkdir(parents=True)
    assert manager.configure()['managed'] == 15
    assert care.BLOCK in (new / 'AGENTS.md').read_bytes()
    manager.configure(False)
    later = manager.home / '.local/share/phasezero/codex/later-profile/native'
    later.mkdir(parents=True)
    manager.configure()
    assert not (later / 'AGENTS.md').exists()


def test_codex_override_is_effective_target_and_original_stays_restorable(manager):
    target, original = personal(manager)
    manager.configure(True)
    override = target.with_name('AGENTS.override.md')
    override.write_text('# Outro perfil\n')
    manager.configure()
    assert care.BLOCK in override.read_bytes()
    manager.configure(False)
    assert target.read_bytes() == original
    assert override.read_text() == '# Outro perfil\n'


@pytest.mark.parametrize('problem', ['symlink', 'writable', 'encoding', 'size', 'unknown-marker'])
def test_unknown_target_blocks_batch_before_any_instruction_write(manager, problem):
    target, original = personal(manager)
    if problem == 'symlink':
        target.unlink()
        target.symlink_to(manager.home / 'private-other-file')
    elif problem == 'writable':
        target.chmod(0o666)
    elif problem == 'encoding':
        target.write_bytes(b'\xff\xfe')
    elif problem == 'size':
        target.write_bytes(b'x' * 65537)
    else:
        target.write_bytes(original + care.BEGIN + b'\ntexto de outro owner\n' + care.END)
    with pytest.raises((ValueError, OSError)):
        manager.configure(True)
    assert not manager.state.exists()
    assert not (manager.home / '.claude/CLAUDE.md').exists()


def test_external_managed_block_edit_stops_sync_and_disable_preserves_everything(manager):
    target, _ = personal(manager)
    manager.configure(True)
    target.write_bytes(target.read_bytes().replace(b'Uma carga', b'Duas cargas'))
    changed = target.read_bytes()
    assert manager.status()['state'] == 'conflict'
    with pytest.raises(ValueError): manager.configure()
    with pytest.raises(ValueError): manager.configure(False)
    assert target.read_bytes() == changed and manager.preference() is False


def test_interruption_never_replays_and_manual_disable_recovers_partial(manager, monkeypatch):
    target, original = personal(manager)
    real = manager._write
    calls = []
    def interrupted(path, expected, desired):
        calls.append(path)
        if len(calls) == 2: raise OSError('interrompido')
        real(path, expected, desired)
    monkeypatch.setattr(manager, '_write', interrupted)
    result = manager.configure(True)
    assert result['outcome'] == 'desconhecido'
    assert manager.configure()['operation_id'] == result['operation_id']
    assert len(calls) == 2
    assert manager.configure(reconcile=True)['outcome'] == 'desconhecido'
    monkeypatch.setattr(manager, '_write', real)
    assert manager.configure(False)['state'] == 'restored'
    assert target.read_bytes() == original


def test_completed_effects_reconcile_same_id_without_rewrite(manager, monkeypatch):
    result = manager.configure(True)
    row = json.loads(manager.state.read_text()); row['phase'] = 'intended'
    manager.state.write_text(json.dumps(row))
    monkeypatch.setattr(manager, '_write', lambda *_: pytest.fail('replay'))
    result2 = manager.configure(reconcile=True)
    assert result2['state'] == 'applied' and result2['operation_id'] == result['operation_id']


@pytest.mark.parametrize('corruption', ['path', 'hash', 'schema', 'effect'])
def test_corrupt_receipt_cannot_write_or_erase_personal_instructions(manager, corruption):
    target, _ = personal(manager)
    manager.configure(True)
    before = target.read_bytes()
    row = json.loads(manager.state.read_text())
    if corruption == 'path': row['entries'][0]['path'] = str(manager.home / '.ssh/config')
    elif corruption == 'hash': row['entries'][0]['before']['sha256'] = '0' * 64
    elif corruption == 'schema': row['schema'] = 999
    else: row['changes'][0]['after']['data'] = base64.b64encode(b'other').decode()
    manager.state.write_text(json.dumps(row))
    with pytest.raises((ValueError, KeyError)): manager.configure(False)
    assert target.read_bytes() == before and manager.preference() is False


def test_write_revalidation_protects_a_file_changed_after_intent(manager, monkeypatch):
    target, original = personal(manager)
    real = manager._write
    def raced(path, expected, desired):
        if path == target: target.write_bytes(original + b'# concurrent\n')
        real(path, expected, desired)
    monkeypatch.setattr(manager, '_write', raced)
    assert manager.configure(True)['outcome'] == 'desconhecido'
    assert target.read_bytes() == original + b'# concurrent\n'


@pytest.mark.parametrize('interrupted_mode_change', [False, True])
def test_verified_manual_migration_restores_pre_guidance_bytes(manager, tmp_path, interrupted_mode_change):
    target, original = personal(manager)
    source = (Path(__file__).parents[1] / 'AGENTS.md').read_bytes()
    a, b = source.index(care.LEGACY_BEGIN), source.index(care.LEGACY_END) + len(care.LEGACY_END)
    block = source[a:b]
    assert hashlib.sha256(block).hexdigest() == care.LEGACY_SHA
    deployed = original + b'\n\n' + block + b'\n'
    target.write_bytes(deployed)
    backup = tmp_path / 'migration'; backup.mkdir(mode=0o700)
    (backup / '00.before').write_bytes(original)
    manifest = backup / 'manifest.json'
    manifest.write_text(json.dumps({'files': [{'path': str(target), 'backup': '00.before',
        'existed': True, 'mode': '0o640', 'before_sha256': care._hash(original),
        'after_sha256': care._hash(deployed)}]})); manifest.chmod(0o600)
    assert manager.configure(True, adopt=manifest)['ok']
    assert target.read_bytes().startswith(original) and care.LEGACY_BEGIN not in target.read_bytes()
    if interrupted_mode_change:
        target.write_bytes(deployed); target.chmod(0o600)
        row = json.loads(manager.state.read_text()); row['phase'] = 'intended'
        manager.state.write_text(json.dumps(row))
        with pytest.raises(ValueError, match='manual divergente'): manager.configure(False)
        assert not manager.preference() and target.read_bytes() == deployed
        return
    assert manager.configure(False)['ok']
    assert target.read_bytes() == original


def test_cli_requires_confirmation_and_cold_status_does_not_enable(manager, capsys):
    assert cli.main(['ai', 'care-enable', '--json']) != 0
    assert not manager.state.exists()
    assert cli.main(['ai', 'care-status', '--json']) == 0
    assert cli.main(['ai', 'care-sync', '--json']) == 0
    assert not manager.config.exists()
    assert cli.main(['ai', 'care-enable', '--confirmar', '--json']) == 0
    assert cli.main(['ai', 'care-disable', '--confirmar', '--json']) == 0
    assert not manager.preference()
    assert 'enabled' in capsys.readouterr().out


def test_xdg_config_outside_home_is_supported_without_searching_other_directories(manager, tmp_path, monkeypatch):
    config = tmp_path / 'private-config'
    (config / 'Code/User').mkdir(parents=True)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config))
    manager = care.AgentGuidelines()
    assert manager.configure(True)['ok']
    assert care.BLOCK in (config / 'Code/User/prompts/host-care.instructions.md').read_bytes()
    manager.configure(False)
    assert not (config / 'Code/User/prompts/host-care.instructions.md').exists()


def test_hardlinked_instructions_remain_protected(manager):
    target, original = personal(manager)
    import os
    os.link(target, manager.home / 'other-instructions.md')
    with pytest.raises(ValueError, match='links'): manager.configure(True)
    assert target.read_bytes() == original and target.stat().st_nlink == 2


def test_receipt_budget_refuses_before_first_effect(manager, monkeypatch):
    target, original = personal(manager)
    monkeypatch.setattr(care, 'MAX_RECEIPT', 100)
    with pytest.raises(ValueError, match='MiB'): manager.configure(True)
    assert target.read_bytes() == original and not manager.preference()


@pytest.mark.parametrize('enabled', [True, False, None])
def test_unknown_preference_schema_is_preserved_for_all_entrypoints(manager, enabled):
    manager.config.parent.mkdir(parents=True)
    unknown = b'{"schema":999,"enabled":true,"personal":"preserve"}'
    manager.config.write_bytes(unknown); manager.config.chmod(0o600)
    with pytest.raises(ValueError): manager.configure(enabled)
    assert manager.config.read_bytes() == unknown
    assert not manager.state.exists() and not (manager.home / '.codex/AGENTS.md').exists()


def test_other_editor_extensions_do_not_invent_a_continue_installation(manager):
    (manager.home / '.continue').rmdir()
    (manager.home / '.vscode/extensions/other.extension-1').mkdir(parents=True)
    assert str(manager.home / '.continue/rules/host-care.md') not in manager._catalog()
