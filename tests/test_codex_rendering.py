import json

import pytest

from folego.actions.codex_rendering import (CodexRendering, RenderingError,
                                          RenderingUnconfirmed, HEADER, FLAGS, digest)
from folego.orchestration.coordinator import Coordinator


@pytest.fixture
def profile(tmp_path):
    target = tmp_path / 'config/codex-desktop/electron-flags.conf'
    target.parent.mkdir(parents=True)
    target.write_text(HEADER + '\n# keep comment\n--disable-gpu\n--force-renderer-accessibility\n')
    target.chmod(0o600)
    return CodexRendering(target=target, state=tmp_path / 'state/receipt.json',
                          coordinator=Coordinator(lock_path=tmp_path / 'lock'))


def test_persistent_software_preserves_preferences_and_exact_restore(profile):
    before = profile.target.read_bytes()
    assert not profile.status()['enabled']
    applied = profile.apply()
    text = profile.target.read_text()
    assert applied['enabled'] and applied['outcome'] == 'sucesso'
    assert all(flag in text for flag in FLAGS)
    assert '--disable-gpu\n' not in text and '--force-renderer-accessibility' in text
    assert '# keep comment' in text
    again = profile.apply()
    assert again['operation_id'] == applied['operation_id']
    assert profile.target.read_text() == text
    assert not profile.apply(restore=True)['enabled']
    assert profile.target.read_bytes() == before
    assert not profile.state.stat().st_mode & 0o077


def test_durable_intent_precedes_effect_and_crash_is_reconciled(profile, monkeypatch):
    from folego.actions import codex_rendering as module
    write = module.write_atomic
    def crash(path, data, **kwargs):
        if path == profile.target:
            row = json.loads(profile.state.read_text())
            assert row['phase'] == 'intent'
            assert row['before_hash'] == digest(profile.target.read_bytes())
            write(path, data, **kwargs)
            raise OSError('simulated crash after replacement')
        return write(path, data, **kwargs)
    monkeypatch.setattr(module, 'write_atomic', crash)
    with pytest.raises(RenderingUnconfirmed): profile.apply()
    row = json.loads(profile.state.read_text())
    status = profile.status()
    assert status['enabled'] and status['state'] == 'pending'
    assert not status['can_apply'] and status['can_restore']
    monkeypatch.setattr(module, 'write_atomic', write)
    assert profile.apply()['operation_id'] == row['operation_id']
    assert profile.apply(restore=True)['state'] == 'unchanged'


@pytest.mark.parametrize('change', ['user-edit', 'corrupt-receipt', 'unknown-schema', 'symlink', 'unsafe-mode'])
def test_uncertain_or_changed_sources_refuse_without_writing(profile, change, tmp_path):
    profile.apply()
    if change == 'user-edit': profile.target.write_text(profile.target.read_text() + '--x11\n')
    if change == 'corrupt-receipt': profile.state.write_text('{')
    if change == 'unknown-schema':
        row = json.loads(profile.state.read_text()); row['schema'] = 2
        profile.state.write_text(json.dumps(row))
    if change == 'symlink':
        original = profile.target.read_bytes()
        other = tmp_path / 'other'; other.write_bytes(original)
        profile.target.unlink(); profile.target.symlink_to(other)
    if change == 'unsafe-mode': profile.target.chmod(0o666)
    before = profile.target.read_bytes()
    with pytest.raises((RenderingError, OSError)): profile.apply(restore=True)
    assert profile.target.read_bytes() == before


@pytest.mark.parametrize('flag', ['--disable-software-rasterizer', '--use-angle=metal', '--use-gl', 'not-a-flag'])
def test_incompatible_configuration_is_not_silently_replaced(profile, flag):
    profile.target.write_text(HEADER + '\n' + flag + '\n')
    before = profile.target.read_bytes()
    with pytest.raises(RenderingError): profile.apply()
    assert profile.target.read_bytes() == before and not profile.state.exists()


def test_change_at_effect_time_blocks_replacement(profile, monkeypatch):
    save = profile._save
    def concurrent_edit(row):
        save(row)
        profile.target.write_text(HEADER + '\n--x11\n')
    monkeypatch.setattr(profile, '_save', concurrent_edit)
    with pytest.raises(RenderingError, match='durante'): profile.apply()
    assert '--x11' in profile.target.read_text()


def test_cli_requires_confirmation_and_works_without_qt(profile, monkeypatch, capsys):
    from folego import cli
    monkeypatch.setattr('folego.actions.codex_rendering.CodexRendering', lambda: profile)
    assert cli.main(['ai', 'render-software', '--json']) != 0
    assert not profile.state.exists()
    capsys.readouterr()
    assert cli.main(['ai', 'render-software', '--json', '--confirmar']) == 0
    assert json.loads(capsys.readouterr().out)['enabled']


def test_auditor_blocks_rendering_effect(profile, tmp_path, monkeypatch):
    from folego import audit_profile

    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'audit-config'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'audit-state'))
    assert audit_profile.configure(True)['enabled']
    original = profile.target.read_bytes()
    with pytest.raises(RenderingError, match='Modo Auditor'):
        profile.apply()
    assert profile.target.read_bytes() == original
    assert not profile.state.exists()


def test_cli_reports_uncertain_effect_as_unknown(profile, monkeypatch, capsys):
    from folego import cli
    monkeypatch.setattr('folego.actions.codex_rendering.CodexRendering', lambda: profile)
    def uncertain(**kwargs): raise RenderingUnconfirmed('verify first', operation_id='known-id')
    monkeypatch.setattr(profile, 'apply', uncertain)
    assert cli.main(['ai', 'render-software', '--json', '--confirmar']) == 5
    result = json.loads(capsys.readouterr().out)
    assert result['outcome'] == 'desconhecido' and result['operation_id'] == 'known-id'


@pytest.mark.parametrize('change', ['permissions', 'undo-by-hand', 'restored-but-reapplied'])
def test_external_changes_preserve_contents_and_permissions(profile, change):
    before = profile.target.read_bytes()
    profile.apply()
    after = profile.target.read_bytes()
    if change == 'permissions': profile.target.chmod(0o644)
    if change == 'undo-by-hand': profile.target.write_bytes(before)
    if change == 'restored-but-reapplied':
        profile.apply(restore=True)
        profile.target.write_bytes(after)
    current, mode = profile.target.read_bytes(), profile.target.stat().st_mode
    status = profile.status()
    assert status['state'] == 'conflict'
    assert not status['can_apply'] and not status['can_restore']
    for restore in (False, True):
        with pytest.raises(RenderingError): profile.apply(restore=restore)
    assert profile.target.read_bytes() == current and profile.target.stat().st_mode == mode


@pytest.mark.parametrize('content', [b'', b'unknown format\n', (HEADER + '\n--use-angle=metal\n').encode()])
def test_unknown_format_is_not_reported_as_original(profile, content):
    profile.target.write_bytes(content)
    with pytest.raises(RenderingError): profile.status()
    assert not profile.state.exists() and profile.target.read_bytes() == content


def test_boolean_schema_is_not_a_supported_receipt(profile):
    profile.apply()
    row = json.loads(profile.state.read_text())
    row['schema'] = True
    profile.state.write_text(json.dumps(row))
    with pytest.raises(RenderingError): profile.status()


def test_receipt_commit_failure_preserves_id_for_consultation(profile, monkeypatch):
    save = profile._save
    def fail_result(row):
        if row['phase'] == 'applied': raise OSError('receipt unavailable')
        save(row)
    monkeypatch.setattr(profile, '_save', fail_result)
    with pytest.raises(RenderingUnconfirmed) as caught: profile.apply()
    assert caught.value.operation_id == json.loads(profile.state.read_text())['operation_id']
    assert profile.status()['state'] == 'pending'


def test_cli_uses_xdg_profile_in_a_separate_process(profile, tmp_path):
    import os
    import subprocess
    import sys
    env = {**os.environ, 'XDG_CONFIG_HOME': str(profile.target.parents[1]),
           'XDG_STATE_HOME': str(tmp_path / 'xdg-state')}
    def call(*args):
        done = subprocess.run([sys.executable, '-m', 'folego', 'ai', *args, '--json'],
                              env=env, capture_output=True, text=True, timeout=15)
        assert done.returncode == 0, done.stderr + done.stdout
        return json.loads(done.stdout)
    before = profile.target.read_bytes()
    assert call('render-status')['can_apply']
    applied = call('render-software', '--confirmar')
    assert applied['enabled'] and call('render-status')['operation_id'] == applied['operation_id']
    assert not call('render-restore', '--confirmar')['enabled']
    assert profile.target.read_bytes() == before
