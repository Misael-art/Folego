from folego.core import agent_pressure


def test_advisory_expires_and_attention_is_bounded(tmp_path):
    runtime = tmp_path / 'runtime'
    runtime.mkdir(mode=0o700)
    issued = agent_pressure.publish('danger', runtime=runtime, clock=lambda: 100)
    assert agent_pressure.current(runtime=runtime, clock=lambda: 101)['id'] == issued['id']
    assert agent_pressure.publish('danger', runtime=runtime, clock=lambda: 120)['id'] == issued['id']
    assert agent_pressure.acknowledge(issued, runtime=runtime, clock=lambda: 121)
    receipt = agent_pressure.receipt(issued, runtime=runtime, clock=lambda: 122)
    assert receipt['request_id'] == issued['id']
    renewed = agent_pressure.publish('danger', runtime=runtime, clock=lambda: 165)
    assert renewed['id'] != issued['id']
    assert agent_pressure.receipt(renewed, runtime=runtime, clock=lambda: 166) is None
    assert agent_pressure.current(runtime=runtime, clock=lambda: 256) is None
    event = agent_pressure.attention('PermissionRequest', runtime=runtime, clock=lambda: 200)
    assert agent_pressure.latest_attention(runtime=runtime, clock=lambda: 201)['id'] == event['id']
    assert agent_pressure.latest_attention(runtime=runtime, clock=lambda: 261) is None
    agent_pressure.clear(runtime=runtime)
    assert agent_pressure.current(runtime=runtime, clock=lambda: 101) is None


def test_shared_runtime_is_refused(tmp_path):
    import pytest
    runtime = tmp_path / 'runtime'
    runtime.mkdir(mode=0o777)
    runtime.chmod(0o777)
    with pytest.raises(ValueError, match='compartilhado'):
        agent_pressure.publish('danger', runtime=runtime)


def test_codex_hook_adds_advice_only_for_current_request(tmp_path, monkeypatch, capsys):
    import io
    import json
    from folego import agent_hook
    runtime = tmp_path / 'runtime'
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(runtime))
    request = agent_pressure.publish('critical', runtime=runtime)
    monkeypatch.setattr('sys.stdin', io.StringIO('{"hook_event_name":"PreToolUse"}'))
    agent_hook.main()
    output = json.loads(capsys.readouterr().out)
    assert request['id'] in output['hookSpecificOutput']['additionalContext']
    assert agent_pressure.receipt(request, runtime=runtime) is not None
    assert agent_pressure.PressureBackend().perform('status')['delivery_confirmed'] is True
    assert 'não comprovada' in agent_pressure.PressureBackend().perform('status')['message']
    monkeypatch.setattr('sys.stdin', io.StringIO('{"hook_event_name":"Stop"}'))
    agent_hook.main()
    assert capsys.readouterr().out == ''
    assert agent_pressure.latest_attention(runtime=runtime)['kind'] == 'Stop'
    agent_pressure.clear(runtime=runtime)
    monkeypatch.setattr('sys.stdin', io.StringIO('{"hook_event_name":"PreToolUse"}'))
    agent_hook.main()
    assert capsys.readouterr().out == ''
