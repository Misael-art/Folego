import subprocess

import pytest

from folego.adapters.keyboard_focus import ensure, GROUP, DESCRIPTION


def test_no_focus_rule_preserves_all_other_rules_and_is_bounded(monkeypatch):
    monkeypatch.setattr('folego.adapters.keyboard_focus.shutil.which', lambda name: name)
    config = {('General', 'rules'): 'personal-rule', ('personal-rule', 'title'): 'Personal'}
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == 'qdbus6': return subprocess.CompletedProcess(argv, 0, '', '')
        group, key = argv[argv.index('--group') + 1], argv[argv.index('--key') + 1]
        if argv[0] == 'kwriteconfig6': config[group, key] = argv[-1]
        return subprocess.CompletedProcess(argv, 0, config.get((group, key), ''), '')
    ensure({}, run)
    assert config['personal-rule', 'title'] == 'Personal'
    assert config[GROUP, 'acceptfocus'] == 'false'
    assert config[GROUP, 'title'].startswith('^Fôlego — teclado ')
    assert config[GROUP, 'wmclass'] == 'folego'
    assert config['General', 'rules'] == 'personal-rule,' + GROUP
    calls.clear()
    ensure({}, run)
    assert not any(c[0] == 'kwriteconfig6' for c in calls)


def test_unknown_rule_owner_is_not_overwritten(monkeypatch):
    monkeypatch.setattr('folego.adapters.keyboard_focus.shutil.which', lambda name: name)
    def run(argv, **kwargs):
        assert argv[0] != 'kwriteconfig6'
        text = 'another owner' if argv[-1] == 'Description' else GROUP
        return subprocess.CompletedProcess(argv, 0, text, '')
    with pytest.raises(RuntimeError): ensure({}, run)
