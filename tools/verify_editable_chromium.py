#!/usr/bin/env python3
"""Verify whole-field deletion against DOM state in an owned Chromium profile."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    root = args.state.resolve(); root.mkdir(mode=0o700, parents=True, exist_ok=False)
    for key, folder in (('HOME', 'home'), ('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                        ('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache'), ('TMPDIR', 'tmp')):
        path = root / folder; path.mkdir(mode=0o700); os.environ[key] = str(path)
    for key in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'GROK_HOME'): os.environ.pop(key, None)
    os.environ['PULSE_SERVER'] = 'unix:' + str(root / 'no-audio')
    page = root / 'editor.html'
    page.write_text('''<!doctype html><title>Folego QA Chromium editor</title>
<style>body{background:#18212c;color:white;font:20px sans-serif} [contenteditable],textarea{display:block;width:500px;min-height:100px;background:#eee;color:#111;margin:20px}</style>
<p>Editor próprio de QA — nenhum texto do usuário</p>
<div id="editor" contenteditable="true" role="textbox" aria-label="Editor próprio"></div>
<textarea id="plain" aria-label="Campo próprio"></textarea>
<script>let saved=''; const e=document.getElementById('editor');
e.addEventListener('input',()=>saved=e.textContent);
setInterval(()=>{if(e.textContent!==saved)e.textContent=saved},100);
window.prepare=(id,selected)=>{let f=document.getElementById(id);if(id==='editor'){saved='123 Exemplo';f.innerText=saved;}else f.value='123 Exemplo';f.focus();
if(selected){if(id==='editor'){let r=document.createRange();r.selectNodeContents(f);let s=getSelection();s.removeAllRanges();s.addRange(r)}else f.select()}};
</script>''')
    from PySide6.QtCore import QUrl, QCoreApplication, QEvent
    from PySide6.QtWebSockets import QWebSocket
    from PySide6.QtWidgets import QApplication
    from folego.ui.desktop_shortcuts import ShortcutTabs
    from urllib.request import urlopen
    app = QApplication([]); app.setApplicationName('folego')
    tabs = ShortcutTabs(); tabs.show()
    messages = []; tabs.controller.result.connect(messages.append)
    def wait(predicate, seconds=10):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            if predicate(): return
            time.sleep(.02)
        raise AssertionError('Owned Chromium QA deadline')
    browser = None; ws = QWebSocket(); replies = {}; sequence = 0
    ws.textMessageReceived.connect(lambda raw: replies.update({json.loads(raw)['id']: json.loads(raw)}) if 'id' in json.loads(raw) else None)
    def evaluate(code):
        nonlocal sequence
        sequence += 1; key = sequence
        ws.sendTextMessage(json.dumps(dict(id=key, method='Runtime.evaluate', params=dict(expression=code, returnByValue=True))))
        wait(lambda: key in replies)
        result = replies.pop(key)
        assert 'error' not in result and 'exceptionDetails' not in result.get('result', {}), result
        return result['result']['result'].get('value')
    records = []
    try:
        with (root / 'browser.log').open('w') as log:
            browser = subprocess.Popen(['/opt/google/chrome/chrome', '--user-data-dir=' + str(root / 'profile'),
                '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-sync',
                '--disable-extensions', '--force-renderer-accessibility', '--remote-debugging-port=0',
                '--ozone-platform=' + os.environ.get('XDG_SESSION_TYPE', 'wayland'), '--app=' + page.as_uri()], stdout=log, stderr=log)
        port_file = root / 'profile/DevToolsActivePort'; wait(port_file.exists)
        port = int(port_file.read_text().splitlines()[0])
        with urlopen(f'http://127.0.0.1:{port}/json/list', timeout=3) as response:
            target = next(t for t in json.load(response) if t.get('url') == page.as_uri())
        ws.open(QUrl(target['webSocketDebuggerUrl'])); wait(lambda: ws.isValid())
        wait(lambda: evaluate('typeof prepare') == 'function')
        def activate():
            windows = []
            def mapped():
                nonlocal windows
                result = subprocess.run(['kdotool', 'search', '--all', '--pid', str(browser.pid)], capture_output=True, text=True)
                windows = result.stdout.strip().splitlines()
                return len(windows) == 1
            wait(mapped)
            caption = subprocess.check_output(['kdotool', 'getwindowname', windows[0]], text=True).strip()
            assert 'Folego QA Chromium editor' in caption, caption
            subprocess.run(['kdotool', 'windowactivate', windows[0]], check=True)
        for element in ('editor', 'plain'):
            for selected in (False, True):
                activate(); evaluate('prepare(' + json.dumps(element) + ',' + json.dumps(selected) + ')')
                wait(lambda: evaluate('document.hasFocus()'))
                from folego.adapters.editable_text import Atspi
                import ctypes as C
                api = Atspi()
                try:
                    desk = api.call('get_desktop', 0, error=False, own=True)
                    apps = [api.call('accessible_get_child_at_index', desk, i, own=True) for i in range(api.call('accessible_get_child_count', desk))]
                    queue = [a for a in apps if a and api.call('accessible_get_process_id', a) == browser.pid]
                    focused = []
                    for obj in queue:
                        states = api.call('accessible_get_state_set', obj, error=False, own=True)
                        flags = [s for s in (7, 8, 12, 25) if states and api.call('state_set_contains', states, s, error=False)]
                        if 12 in flags:
                            ptr = api.call('accessible_get_role_name', obj)
                            try: role = C.string_at(ptr).decode() if ptr else ''
                            finally:
                                if ptr: api.glib.g_free(ptr)
                            focused.append(dict(role=role, flags=flags,
                                text=bool(api.call('accessible_get_text_iface', obj, error=False, own=True)),
                                editable=bool(api.call('accessible_get_editable_text_iface', obj, error=False, own=True))))
                        count = api.call('accessible_get_child_count', obj)
                        assert len(queue) + count < 2048
                        queue.extend(api.call('accessible_get_child_at_index', obj, i, own=True) for i in range(count))
                    print(json.dumps(dict(focused=focused)), flush=True)
                finally: api.close()
                assert tabs.controller.request('delete_all')
                wait(lambda: tabs.controller.future is None)
                # Wait beyond the controlled editor's state reconciliation.
                end = time.monotonic() + .4
                while time.monotonic() < end: app.processEvents(); time.sleep(.02)
                actual = evaluate("document.getElementById(" + json.dumps(element) + ")." + ('textContent' if element == 'editor' else 'value'))
                record = dict(element=element, selected=selected, empty=actual == '', actual=actual,
                              saved=evaluate('saved'), selection=evaluate('getSelection().toString()'), feedback=messages[-1] if messages else '')
                records.append(record); print(json.dumps(record), flush=True)
        result = dict(passed=all(r['empty'] for r in records), cases=records, scope='owned Chrome profile, DOM checked after controlled-input reconciliation')
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        assert result['passed']
    finally:
        ws.close(); tabs.shutdown(); tabs.close()
        if browser is not None and browser.poll() is None:
            browser.terminate(); browser.wait(timeout=8)  # exact QA Popen child only
        for widget in list(app.topLevelWidgets()): widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()


if __name__ == '__main__': main()
