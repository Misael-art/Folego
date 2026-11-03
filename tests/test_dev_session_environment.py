import importlib.util
import os
from pathlib import Path


def test_disposable_qa_cannot_inherit_native_provider_credentials(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / 'tools/dev_session.py'
    spec = importlib.util.spec_from_file_location('folego_dev_session_qa', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    names = ('CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'GROK_HOME')
    for name in names: monkeypatch.setenv(name, '/physical-user/private-provider')
    monkeypatch.setenv('PULSE_SERVER', 'unix:/physical-user/audio')
    private = module.test_environment(tmp_path)
    assert all(name not in private for name in names)
    assert private['HOME'] == str(tmp_path/'home')
    assert private['PULSE_SERVER'] == 'unix:' + str(tmp_path/'no-audio-server')
    assert os.environ['PULSE_SERVER'] == 'unix:/physical-user/audio'
    assert all(os.environ[name] == '/physical-user/private-provider' for name in names)
