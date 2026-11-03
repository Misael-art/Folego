#!/usr/bin/env python3
"""Native completion badges and confirmed focus, using only owned QA sessions.

The provider-window lookup is substituted by one exact owned window. Activation,
identity checks, the asynchronous button path and durable acknowledgement are
the production implementation. No real agent/application is opened or closed.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    root = args.state.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    for key, folder in (('HOME', 'home'), ('XDG_CONFIG_HOME', 'config'),
                        ('XDG_DATA_HOME', 'data'), ('XDG_STATE_HOME', 'state'),
                        ('XDG_CACHE_HOME', 'cache'), ('TMPDIR', 'tmp')):
        path = root / folder
        path.mkdir(mode=0o700)
        os.environ[key] = str(path)
    for key in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'GROK_HOME'):
        os.environ.pop(key, None)
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QLineEdit
    from folego.adapters.agent_apps import AgentApps
    from folego.core.agent_deliveries import DeliveryMonitor
    from folego.ui.compact import CompactWindow
    from folego.ui.desktop_caps import detect
    from folego.ui.theme import apply_theme
    app = QApplication([])
    assert app.platformName() == 'wayland'
    apply_theme(app)
    target = QLineEdit()
    target.setWindowTitle('Folego deliveries QA owned target')
    target.show()
    home = root / 'home'
    monitor = DeliveryMonitor(discover=lambda: [])
    config = root / 'config/folego/ai-sessions.json'
    config.parent.mkdir(parents=True, exist_ok=True)
    second = home / '.codex-work'
    config.write_text(json.dumps(dict(schema=1, accounts=[dict(provider='codex', path=str(second), label='Trabalho')])))
    monitor.collect()  # configured roots and epoch, before synthetic completions
    from folego.core.ai_accounts import inventory
    from folego.core import ai_sessions as ai
    accounts = inventory()
    default_id = next(a['account_id'] for a in accounts if a['provider'] == 'codex' and a['default'])
    work_id = next(a['account_id'] for a in accounts if a['path'] == str(second))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    def write(path, records):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in records))
    for n in range(2):
        write(home / f'.codex/sessions/2026/11/01/rollout-{n}.jsonl', [
            dict(type='session_meta', payload=dict(id=str(n), source='cli')),
            dict(timestamp=now, type='event_msg', payload=dict(type='task_complete', turn_id=str(n)))])
    write(second / 'sessions/2026/11/01/rollout-work.jsonl', [
        dict(type='session_meta', payload=dict(id='work', source='cli')),
        dict(timestamp=now, type='event_msg', payload=dict(type='task_complete', turn_id='work'))])
    for n in range(5):
        write(home / f'.claude/projects/qa/{n}.jsonl', [
            dict(timestamp=now, type='assistant', uuid=str(n),
                 message=dict(stop_reason='end_turn', content=[dict(type='text', text='QA')]))])
    write(home / '.grok/sessions/qa/one/updates.jsonl', [
        dict(timestamp=now, params=dict(update=dict(sessionUpdate='turn_completed',
                                                  stop_reason='end_turn', prompt_id='qa')))])
    class OwnedApps(AgentApps):
        def _windows(self, binary, provider, account=None):
            result = self._call([binary, 'search', '--all', '--pid', str(os.getpid()),
                                 '--name', '^Folego deliveries QA owned target$'], search=True)
            return result.splitlines()
    class Host:
        def raise_to_user(self): pass
        def quit(self): app.quit()
    class Store:
        def value(self, key, default=None): return default
        def setValue(self, key, value): pass
        def sync(self): pass
    view = CompactWindow(Host(), caps=detect(session_type='wayland', platform='wayland'), store=Store())
    strip = view.ai_strip
    strip.deliveries = monitor
    strip.delivery_poller._collect = monitor.collect
    strip.opener.backend = OwnedApps(monitor)
    items = []
    for account in accounts:
        item = ai.unknown(account['provider'], label=account['label'])
        item.update(account_id=account['account_id'], default=account['default'])
        items.append(item)
    strip.poller._collect = lambda: items  # no credential/network reads in QA
    def wait(predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate(): return
            time.sleep(.02)
        raise AssertionError('native delivery QA deadline')
    try:
        view.show_compact()
        wait(lambda: strip.badges['codex'].text() == '3' and strip.badges['claude'].text() == '5')
        assert strip.badges['grok'].text() == '1'
        view.adjustSize()
        assert view.width() == 280
        view.grab().save(str(root / 'before.png'))
        strip.set_items(items)
        strip.buttons['codex'].click()
        wait(lambda: target.isActiveWindow() and strip.badges['codex'].text() == '1')
        assert next(r for r in monitor.collect() if r['provider'] == 'codex')['pending'][0]['account_id'] == work_id
        strip.open_agent('codex', work_id)
        wait(lambda: strip.badges['codex'].text() == '')
        assert strip.badges['claude'].text() == '5' and strip.badges['grok'].text() == '1'
        reopened = DeliveryMonitor(discover=lambda: []).collect()
        assert next(r for r in reopened if r['provider'] == 'codex')['count'] == 0
        view.grab().save(str(root / 'after.png'))
        result = dict(passed=True, platform=app.platformName(), size=[view.width(), view.height()],
                      before=dict(codex=3, claude=5, grok=1), after=dict(codex=0, claude=5, grok=1),
                      focused_owned_target=True, durable_receipt=True, account_scoped_ack=True, after_default_codex=1,
                      scope='synthetic transcripts; owned native window; provider lookup substituted')
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))
    finally:
        view.force_close()
        target.close()
        for window in list(app.topLevelWidgets()): window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


if __name__ == '__main__':
    main()
