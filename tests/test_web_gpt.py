import json
from pathlib import Path
from types import SimpleNamespace

from folego.core import web_gpt
from folego.core.ai_accounts import inventory


def test_launcher_process_discovery_uses_owned_package_and_user_data(tmp_path):
    root = tmp_path / '.local/share/vendor/chatgpt-web'
    exe = root / 'packages/6.1.17/app/codex-web-gpt-launcher'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'fixture')
    proc = tmp_path / 'proc'
    user_data = tmp_path / '.config/Codex Web GPT'
    for pid, argv in ((101, [str(exe)]), (102, [str(exe), '--type=renderer',
                                          '--user-data-dir=' + str(user_data)])):
        directory = proc / str(pid)
        directory.mkdir(parents=True)
        (directory / 'exe').symlink_to(exe)
        (directory / 'cmdline').write_bytes('\0'.join(argv).encode() + b'\0')
    found = web_gpt.installed_launchers({'HOME': str(tmp_path)}, proc=proc)
    assert found == [dict(core_home=str(root / 'core-home'), launcher_data=str(user_data),
                          codex_home=str(root / 'codex-home'))]


def test_installed_launcher_is_primary_without_external_roster(tmp_path):
    home = tmp_path
    root = home / '.local/share/vendor/chatgpt-web'
    core = root / 'core-home'
    data = root / 'launcher-data'
    codex = root / 'codex-home'
    for path in (core, data, codex):
        path.mkdir(parents=True)
    env = {'HOME': str(home), 'XDG_DATA_HOME': str(home / '.local/share')}
    rows = inventory(env, discover=lambda: [], discover_web=lambda _env: [
        dict(core_home=str(core), launcher_data=str(data), codex_home=str(codex))])
    current = next(a for a in rows if a['provider'] == 'web' and a['default'])
    assert current['path'] == str(codex)
    assert current['web_core_home'] == str(core)
    assert current['web_launcher_data'] == str(data)


def test_standalone_official_home_is_discovered_without_running_process(tmp_path):
    (tmp_path / '.codex-chatgpt-web').mkdir()
    env = {'HOME': str(tmp_path), 'XDG_CONFIG_HOME': str(tmp_path / '.config')}
    rows = inventory(env, discover=lambda: [], discover_web=lambda _env: [])
    web = next(a for a in rows if a['provider'] == 'web' and a['default'])
    assert web['web_core_home'] == str(tmp_path / '.codex-chatgpt-web')
    assert web['web_launcher_data'] == str(tmp_path / '.config/Codex Web GPT')


def test_corrupt_limits_does_not_hide_independent_service_status(tmp_path):
    core = tmp_path / 'core-home'
    data = tmp_path / 'launcher-data'
    data.mkdir()
    (data / 'limits.json').write_text('{corrupt')
    observed = web_gpt.observe(core, data, now=1000, live=False)
    assert observed['remaining'] is None and observed['windows'] == []
    assert 'histórico local do launcher ilegível' in observed['reason']
    assert observed['web_service']['state'] == 'unknown'


def test_health_requires_expected_service_version_and_turn_acceptance(tmp_path, monkeypatch):
    core = tmp_path / 'core-home'
    core.mkdir()
    (core / 'config.json').write_text(json.dumps(dict(host='127.0.0.1', port=17841,
                                                     mode='full', releaseVersion='6.1.17')))
    response = dict(service='codex-chatgpt-web', status='ok', mode='full', version='6.1.17',
                    accepting_turns=True, last_model_catalog_result=dict(status=200))
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, method, path): assert (method, path) == ('GET', '/healthz')
        def getresponse(self):
            return SimpleNamespace(status=200, read=lambda size: json.dumps(response).encode())
        def close(self): pass
    monkeypatch.setattr(web_gpt.http.client, 'HTTPConnection', Connection)
    assert web_gpt.service_status(core)['state'] == 'ready'
    response['accepting_turns'] = False
    assert web_gpt.service_status(core)['state'] == 'unavailable'
    response['accepting_turns'] = True
    response['version'] = 'other'
    assert web_gpt.service_status(core)['state'] == 'unavailable'


def test_tunnel_probe_is_read_only_cached_and_never_proves_remote_attachment(tmp_path, monkeypatch):
    core = tmp_path / 'core-home'
    binary = core / 'bin/tunnel-client'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'fixture')
    binary.chmod(0o700)
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=json.dumps(dict(apply=False, entries=[
            dict(alias='codex-chatgpt-web', runtime_state='ready', classification='live_runtime')])).encode())
    monkeypatch.setattr(web_gpt.subprocess, 'run', run)
    first = web_gpt.tunnel_status(core, 'codex-chatgpt-web', now=1000)
    second = web_gpt.tunnel_status(core, 'codex-chatgpt-web', now=1001)
    assert first == second == dict(state='ready', detail='Runtime local do túnel pronto')
    assert calls == [[str(binary), 'runtimes', 'cleanup', '--json']]
    web_gpt.tunnel_status(core, 'codex-chatgpt-web', now=1301)
    assert len(calls) == 2


def test_untrusted_tunnel_binary_is_not_executed(tmp_path, monkeypatch):
    binary = tmp_path / 'bin/tunnel-client'
    binary.parent.mkdir()
    binary.write_bytes(b'fixture')
    binary.chmod(0o777)
    monkeypatch.setattr(web_gpt.subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert web_gpt.tunnel_status(tmp_path, 'alias')['state'] == 'unknown'
