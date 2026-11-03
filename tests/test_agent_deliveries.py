import datetime as dt
import json
import sqlite3

import pytest

from folego.core.agent_deliveries import DeliveryMonitor, last_delivery

NOW = 1_700_000_000


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()


def append(path, *rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        for row in rows: stream.write(json.dumps(row) + '\n')


def event(kind, t, turn='turn-1'):
    return dict(timestamp=iso(t), type='event_msg', payload=dict(type=kind, turn_id=turn))


def codex(home, name='one', source='cli'):
    path = home / '.codex/sessions/2026/11/01' / ('rollout-' + name + '.jsonl')
    append(path, dict(type='session_meta', payload=dict(id=name, source=source)))
    return path


def monitor(home, clock):
    return DeliveryMonitor(env={'HOME': str(home)}, state=home / 'folego/deliveries.json',
                           clock=lambda: clock[0], discover=lambda: [])


def row(view, provider='codex'):
    return next(x for x in view.collect() if x['provider'] == provider)


def test_first_activation_ignores_history_then_counts_sessions_once(tmp_path):
    path = codex(tmp_path)
    append(path, event('task_complete', NOW - 10))
    clock = [NOW]
    view = monitor(tmp_path, clock)
    assert row(view)['count'] == 0
    clock[0] += 1
    append(path, event('task_complete', clock[0]))
    assert row(view)['count'] == row(view)['count'] == 1
    assert row(monitor(tmp_path, clock))['count'] == 1
    second = codex(tmp_path, 'two')
    append(second, event('task_complete', clock[0], 'turn-2'))
    assert row(view)['count'] == 2


def test_only_pending_primary_deliveries_not_tools_or_subagents(tmp_path):
    clock = [NOW]
    view = monitor(tmp_path, clock)
    view.collect()
    path = codex(tmp_path)
    child = codex(tmp_path, 'child', {'subagent': 'internal'})
    clock[0] += 1
    append(path, event('item_completed', clock[0]))
    append(child, event('task_complete', clock[0]))
    assert row(view)['count'] == 0
    append(path, event('task_complete', clock[0]))
    assert row(view)['count'] == 1
    append(path, event('task_started', clock[0], 'next'))
    assert row(view)['count'] == 0


def test_acknowledgement_is_durable_and_does_not_clear_a_new_completion(tmp_path):
    clock = [NOW]
    view = monitor(tmp_path, clock)
    view.collect()
    path = codex(tmp_path)
    clock[0] += 1
    append(path, event('task_complete', clock[0]))
    pending = row(view)['pending']
    clock[0] += 1
    append(path, event('task_started', clock[0], 'new'), event('task_complete', clock[0], 'new'))
    view.acknowledge(pending)
    assert row(view)['count'] == 1
    view.acknowledge(row(view)['pending'])
    assert row(monitor(tmp_path, clock))['count'] == 0
    payload = view.state.read_text()
    assert 'rollout' not in payload and 'turn-1' not in payload
    assert view.state.stat().st_mode & 0o077 == 0


def test_unreadable_or_unknown_state_is_not_replaced(tmp_path):
    clock = [NOW]
    view = monitor(tmp_path, clock)
    view.state.parent.mkdir()
    for content in ('{', '{"schema":99,"seen":{}}'):
        view.state.write_text(content)
        with pytest.raises(ValueError): view.collect()
        assert view.state.read_text() == content


def test_torn_source_is_unknown_not_zero(tmp_path):
    clock = [NOW]
    view = monitor(tmp_path, clock)
    view.collect()
    path = codex(tmp_path)
    with path.open('a') as f: f.write('{"type":')
    assert row(view)['count'] is None


def test_claude_final_text_counts_once_and_next_user_prompt_clears(tmp_path):
    clock = [NOW]
    view = monitor(tmp_path, clock)
    view.collect()
    path = tmp_path / '.claude/projects/project/session.jsonl'
    clock[0] += 1
    def assistant(uid, kind, stop='end_turn'):
        return dict(timestamp=iso(clock[0]), type='assistant', uuid=uid, sessionId='session',
                    isSidechain=False, message=dict(stop_reason=stop, content=[dict(type=kind)]))
    append(path, assistant('thinking', 'thinking'), assistant('final', 'text'))
    assert row(view, 'claude')['count'] == 1
    append(path, dict(timestamp=iso(clock[0]), type='user',
                      message=dict(content=[dict(type='tool_result')])))
    assert row(view, 'claude')['count'] == 1
    append(path, dict(timestamp=iso(clock[0]), type='user', message=dict(content='new request')))
    assert row(view, 'claude')['count'] == 0


def test_grok_requires_successful_terminal_event(tmp_path):
    clock = [NOW]
    view = monitor(tmp_path, clock)
    view.collect()
    path = tmp_path / '.grok/sessions/project/session/updates.jsonl'
    clock[0] += 1
    def update(kind, reason=None):
        return dict(timestamp=iso(clock[0]), method='_x.ai/session/update',
                    params=dict(sessionId='session', update=dict(sessionUpdate=kind, stop_reason=reason, prompt_id='p1')))
    append(path, update('agent_message_chunk'))
    assert row(view, 'grok')['count'] == 0
    append(path, update('turn_completed', 'cancelled'))
    assert row(view, 'grok')['count'] == 0
    append(path, update('turn_completed', 'end_turn'))
    assert row(view, 'grok')['count'] == 1
    append(path, update('user_message_chunk'))
    assert row(view, 'grok')['count'] == 0


def test_native_index_excludes_archived_and_internal_sessions(tmp_path):
    clock = [NOW]
    view = monitor(tmp_path, clock)
    view.collect()
    root = tmp_path / '.codex'
    path = codex(tmp_path)
    append(path, event('task_complete', NOW + 1))
    with sqlite3.connect(root / 'state_5.sqlite') as db:
        db.execute('create table threads(rollout_path text,source text,archived int)')
        db.execute('insert into threads values(?,?,?)', (str(path), 'vscode', 1))
    clock[0] += 1
    assert row(view)['count'] == 0
    with sqlite3.connect(root / 'state_5.sqlite') as db: db.execute('update threads set archived=0')
    assert row(view)['count'] == 1
    with sqlite3.connect(root / 'state_5.sqlite') as db: db.execute('update threads set source=?', ('{"subagent":{}}',))
    assert row(view)['count'] == 0


def test_future_clock_is_unknown(tmp_path):
    clock = [NOW]
    view = monitor(tmp_path, clock)
    view.collect()
    path = codex(tmp_path)
    append(path, event('task_complete', NOW + 100))
    assert row(view)['count'] is None


def test_inventory_over_budget_is_unknown_instead_of_sampling(tmp_path):
    clock = [NOW]
    view = monitor(tmp_path, clock)
    view.collect()
    for index in range(129):
        path = codex(tmp_path, str(index))
        append(path, event('task_complete', NOW + 1, str(index)))
    clock[0] += 1
    assert row(view)['count'] is None


def test_completion_outside_read_budget_is_unknown(tmp_path):
    path = codex(tmp_path)
    append(path, event('task_complete', NOW + 1))
    append(path, dict(timestamp=iso(NOW + 1), type='item_completed', data='x' * 70_000))
    with pytest.raises(ValueError): last_delivery('codex', path, NOW, NOW + 2)


def test_malformed_completion_and_relative_account_are_unknown(tmp_path):
    clock = [NOW]
    view = monitor(tmp_path, clock)
    view.collect()
    path = codex(tmp_path)
    append(path, dict(timestamp=iso(NOW + 1), type='event_msg', payload=dict(type='task_complete')))
    clock[0] += 1
    assert row(view)['count'] is None
    config = tmp_path / '.config/folego/ai-sessions.json'
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps(dict(schema=1, accounts=[dict(provider='codex', path='relative')])) )
    with pytest.raises(ValueError): monitor(tmp_path, clock).collect()


def test_partial_scan_preserves_verified_positive_count(tmp_path):
    clock = [NOW]
    view = monitor(tmp_path, clock)
    view.collect()
    completed = codex(tmp_path, 'completed')
    append(completed, event('task_complete', NOW + 1))
    broken = codex(tmp_path, 'unreadable')
    with broken.open('a') as stream: stream.write('{')
    clock[0] += 1
    result = row(view)
    assert result['count'] == 1 and not result['complete']
    view.acknowledge(result['pending'])
    assert row(view)['count'] is None  # partial zero never claims no pending work


def test_old_missing_indexed_session_does_not_create_a_historical_backlog(tmp_path):
    clock = [NOW]
    view = monitor(tmp_path, clock)
    root = tmp_path / '.codex'
    root.mkdir()
    with sqlite3.connect(root / 'state_5.sqlite') as db:
        db.execute('create table threads(rollout_path text,source text,archived int,updated_at int)')
        db.execute('insert into threads values(?,?,?,?)', (str(root / 'missing.jsonl'), 'vscode', 0, NOW - 100))
    assert row(view)['count'] == 0
    with sqlite3.connect(root / 'state_5.sqlite') as db: db.execute('update threads set updated_at=?', (NOW + 1,))
    clock[0] += 1
    assert row(view)['count'] is None


def test_private_home_never_adopts_real_native_account_paths(tmp_path):
    private = tmp_path / 'private'
    private.mkdir()
    external = tmp_path / 'external'
    path = codex(external)
    append(path, event('task_complete', NOW + 1))
    view = DeliveryMonitor(env={'HOME': str(private)}, state=private/'state.json',
          clock=lambda: NOW, discover=lambda: [dict(provider='codex', roots=dict(CODEX_HOME=str(external/'.codex')))])
    assert row(view)['count'] is None
    assert all(str(external) not in directory for _, directory in view._accounts(NOW))
