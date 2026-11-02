#!/usr/bin/env python3
"""Exercise prompt selection and paste only in an owned disposable X server."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--prompt-key', help='Catalog prompt to select and paste; defaults to the first')
    args = parser.parse_args()
    root = args.state.resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    for key, folder in (('HOME', 'home'), ('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                        ('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache'), ('TMPDIR', 'tmp')):
        path = root / folder
        path.mkdir(mode=0o700)
        os.environ[key] = str(path)
    for key in ('WAYLAND_DISPLAY', 'CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'GROK_HOME'):
        os.environ.pop(key, None)
    read, write = os.pipe()
    server = None
    tabs = None
    try:
        with (root / 'xvfb.log').open('w') as log:
            server = subprocess.Popen(['Xvfb', '-displayfd', str(write), '-screen', '0', '1280x800x24',
                                       '-nolisten', 'tcp', '-noreset', '-ac'], pass_fds=(write,), stdout=log, stderr=log)
        os.close(write)
        assert select.select([read], [], [], 8)[0], 'Owned display unavailable'
        display = ':' + os.read(read, 32).decode().strip()
        assert display[1:].isdigit() and server.poll() is None
        os.environ.update(DISPLAY=display, QT_QPA_PLATFORM='xcb', XDG_SESSION_TYPE='x11', QT_QPA_PLATFORMTHEME='generic',
                          DBUS_SESSION_BUS_ADDRESS='unix:path=' + str(root / 'no-session-bus'))
        from PySide6.QtWidgets import QApplication, QTextEdit, QMenu
        from PySide6.QtCore import QCoreApplication, QEvent
        from folego.core.development_prompts import PROMPTS, text
        from folego.ui.desktop_shortcuts import ShortcutTabs
        app = QApplication([])
        selected = next(p for p in PROMPTS if p.key == (args.prompt_key or PROMPTS[0].key))
        field = QTextEdit()
        field.resize(640, 400)
        field.show()
        tabs = ShortcutTabs()
        def wait(predicate):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                app.processEvents()
                if predicate(): return
                time.sleep(.01)
            raise AssertionError('Private clipboard QA deadline')
        tabs.show_prompts()
        wait(lambda: any(m.isVisible() for m in tabs.findChildren(QMenu)))
        menu = next(m for m in tabs.findChildren(QMenu) if m.isVisible())
        next(a for a in menu.actions() if a.text() == selected.title).trigger()
        menu.close()
        wait(lambda: app.clipboard().text() == text(selected.key))
        subprocess.run(['xdotool', 'windowfocus', str(int(field.winId()))], check=True)
        field.setFocus()
        wait(field.hasFocus)
        wait(lambda: tabs.controller.future is None)
        assert tabs.controller.request('paste')
        wait(lambda: tabs.controller.future is None)
        wait(lambda: field.toPlainText() == text(selected.key))
        tabs.show_prompts()
        wait(lambda: tabs.custom_menu is not None and any(a.text() == '123' for a in tabs.custom_menu.actions()))
        next(a for a in tabs.custom_menu.actions() if a.text() == '123').trigger()
        tabs.prompt_menu.close()
        wait(lambda: app.clipboard().text() == '123' and tabs.controller.future is None)
        field.clear()
        subprocess.run(['xdotool', 'windowfocus', str(int(field.winId()))], check=True)
        field.setFocus()
        wait(field.hasFocus)
        assert tabs.controller.request('paste')
        wait(lambda: field.toPlainText() == '123' and tabs.controller.future is None)
        (root / 'result.json').write_text(json.dumps(dict(passed=True,
            case='production menu selection, native clipboard and Shift+Insert into owned editor',
            scope='owned Xvfb only; physical clipboard untouched', prompts=len(PROMPTS),
            selected=selected.key, selected_bytes=len(text(selected.key).encode('utf-8')),
            selected_sha256=hashlib.sha256(text(selected.key).encode('utf-8')).hexdigest(),
            custom_literal='123'), indent=2) + '\n')
        print(json.dumps(dict(passed=True, prompts=len(PROMPTS), scope='private Xvfb')))
        tabs.shutdown()
        for widget in list(app.topLevelWidgets()): widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    finally:
        if tabs is not None: tabs.shutdown()
        os.close(read)
        if server is not None and server.poll() is None:
            server.terminate()  # exact disposable server Popen child
            server.wait(timeout=5)


if __name__ == '__main__':
    main()
