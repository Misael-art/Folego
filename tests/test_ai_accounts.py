import json
from pathlib import Path

import pytest

from folego.core import ai_sessions as ai
from folego.core.ai_accounts import inventory, account_id


def env(home):
    return dict(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'))


def configure(home, **extra):
    path = home / '.config/folego/ai-sessions.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(schema=1, **extra)))
    return path


def roster(home, **extra):
    path = home / '.local/share/phasezero/ai-accounts/codex-profiles/profiles.json'
    path.parent.mkdir(parents=True)
    value = dict(schemaVersion=1, current=dict(label='Pessoal'), profiles=[
        dict(id='pz-0123456789ab', label='Trabalho'),
        dict(id='pz-abcdef012345', label='Arquivada', archived=True)])
    path.write_text(json.dumps(dict(value, **extra)))
    return path


def test_optional_roster_reads_inactive_profiles_without_phasezero_runtime(tmp_path):
    source = roster(tmp_path)
    before = source.read_bytes()
    rows = inventory(env(tmp_path))
    assert len(rows) == 6
    assert not any(a['label'] == 'Arquivada' for a in rows)
    assert [a['label'] for a in rows if a['provider'] == 'codex'] == ['Pessoal', 'Trabalho']
    assert source.read_bytes() == before
    assert not any('phasezero' in key for a in rows for key in a)


def test_native_principal_is_not_replaced_by_agent_environment(tmp_path):
    (tmp_path / '.codex').mkdir()
    other = tmp_path / 'other'
    other.mkdir()
    rows = inventory(dict(env(tmp_path), CODEX_HOME=str(other)))
    codex = [a for a in rows if a['provider'] == 'codex']
    assert len(codex) == 2
    assert next(a for a in codex if a['default'])['path'] == str(tmp_path / '.codex')


def test_roster_does_not_hide_an_existing_standalone_web_account(tmp_path):
    roster(tmp_path)
    standalone = tmp_path / '.local/share/codex-web-gpt/codex-home'
    standalone.mkdir(parents=True)
    rows = inventory(env(tmp_path))
    assert len([a for a in rows if a['provider'] == 'web']) == 3
    assert any(a['path'] == str(standalone) for a in rows)


def test_null_label_is_unknown_configuration_instead_of_a_broken_panel(tmp_path):
    configure(tmp_path, accounts=[dict(provider='codex', path=str(tmp_path / 'other'), label=None)])
    with pytest.raises(ValueError): inventory(env(tmp_path))


def test_explicit_default_label_dedup_and_claude_accounts(tmp_path):
    other = tmp_path / 'claude-work'
    configure(tmp_path, accounts=[dict(provider='claude', path=str(other), label='Empresa', default=True)])
    found = lambda: [dict(provider='claude', roots=dict(CLAUDE_CONFIG_DIR=str(other)))] * 3
    rows = inventory(env(tmp_path), discover=found)
    selected = [a for a in rows if a['provider'] == 'claude' and a['default']]
    assert len(rows) == 5 and len(selected) == 1 and selected[0]['label'] == 'Empresa'
    assert selected[0]['account_id'] == account_id('claude', other)
    assert selected[0]['account_id'] != account_id('codex', other)


@pytest.mark.parametrize('data', [dict(schemaVersion=99), dict(profiles=[dict(id='../escape', label='x')]),
    dict(profiles=[dict(id='pz-0123456789ab', label='x', archived='no')])])
def test_unknown_roster_protects_instead_of_probing_profiles(tmp_path, data):
    roster(tmp_path, **data)
    with pytest.raises(ValueError): inventory(env(tmp_path))
    assert all(i['remaining'] is None and 'Inventário' in i['reason'] for i in ai.collect(env(tmp_path)))


def test_multiple_defaults_are_not_silently_chosen(tmp_path):
    configure(tmp_path, accounts=[dict(provider='grok', path=str(tmp_path / name), default=True)
                                  for name in ('a', 'b')])
    with pytest.raises(ValueError): inventory(env(tmp_path))


def test_monthly_reference_is_scoped_to_selected_account(tmp_path):
    configure(tmp_path, accounts=[dict(provider='codex', path=str(tmp_path / 'other'), label='Segunda')])
    rows = inventory(env(tmp_path))
    second = next(a for a in rows if a['label'] == 'Segunda')
    ai.set_billing_day('codex', 19, second['account_id'], env=env(tmp_path))
    observed = ai.collect(env(tmp_path))
    assert next(i for i in observed if i['account_id'] == second['account_id'])['billing_day'] == 19
    assert all('billing_day' not in i for i in observed if i['account_id'] != second['account_id'])
    before = (tmp_path / '.config/folego/ai-sessions.json').read_bytes()
    with pytest.raises(ValueError): ai.set_billing_day('claude', 19, second['account_id'], env=env(tmp_path))
    assert (tmp_path / '.config/folego/ai-sessions.json').read_bytes() == before


def test_removing_account_reference_does_not_resurrect_legacy_provider_day(tmp_path):
    configure(tmp_path, billing=dict(codex=dict(monthly_day=15)))
    principal = next(a for a in inventory(env(tmp_path)) if a['provider'] == 'codex' and a['default'])
    ai.set_billing_day('codex', 0, principal['account_id'], env=env(tmp_path))
    current = next(i for i in ai.collect(env(tmp_path)) if i['account_id'] == principal['account_id'])
    assert 'billing_day' not in current
