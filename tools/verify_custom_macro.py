#!/usr/bin/env python3
"""Verify desktop macro on an owned KWin/Xvfb, with host runtime hidden.

All activation environment is isolated BEFORE dbus-run-session. Never invokes
showDesktop on the physical session. Requires existing bwrap/Xvfb/kwin_x11.
"""
import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args()
    root = args.state.resolve()
    if not args.child:
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
        env = dict(os.environ)
        for key, folder in (('HOME', 'home'), ('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                            ('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache'),
                            ('XDG_RUNTIME_DIR', 'runtime'), ('TMPDIR', 'tmp')):
            path = root / folder; path.mkdir(mode=0o700); env[key] = str(path)
        for key in ('DBUS_SESSION_BUS_ADDRESS', 'DBUS_STARTER_ADDRESS', 'AT_SPI_BUS_ADDRESS',
                    'WAYLAND_DISPLAY', 'CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'GROK_HOME', 'VIRTUAL_ENV'):
            env.pop(key, None)
        env.update(QT_QPA_PLATFORM='xcb', XDG_SESSION_TYPE='x11', KWIN_COMPOSE='N',
                   QT_QPA_PLATFORMTHEME='generic', PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'),
                   XAUTHORITY=str(root / 'Xauthority'), GTK_USE_PORTAL='0',
                   CUSTOM_QA_HOST_PID_NS=os.readlink('/proc/self/ns/pid'))
        Path(env['XAUTHORITY']).touch(mode=0o600)
        command = ['bwrap', '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc',
                   '--unshare-pid', '--unshare-net', '--new-session',
                   '--tmpfs', f'/run/user/{os.getuid()}', '--bind', str(root), str(root),
                   '--bind', str(root / 'tmp'), '/tmp',
                   'dbus-run-session', '--', sys.executable, str(Path(__file__).resolve()),
                   '--state', str(root), '--child']
        with (root / 'session.log').open('w') as log:
            subprocess.run(command, env=env, stdout=log, stderr=log, check=True, timeout=60)
        print((root / 'result.json').read_text())
        return
    assert os.readlink('/proc/self/ns/pid') != os.environ['CUSTOM_QA_HOST_PID_NS']
    assert Path(os.environ['XDG_RUNTIME_DIR']).is_relative_to(root)
    assert Path(os.environ['HOME']).is_relative_to(root)
    def call(argv): return subprocess.check_output(argv, text=True, timeout=4).strip()
    assert subprocess.run(['qdbus6', 'org.freedesktop.DBus', '/org/freedesktop/DBus',
        'org.freedesktop.DBus.NameHasOwner', 'org.kde.KWin'], capture_output=True, text=True).stdout.strip() == 'false'
    read, write = os.pipe()
    server = manager = tabs = None
    try:
        with (root / 'xvfb.log').open('w') as log:
            server = subprocess.Popen(['Xvfb', '-displayfd', str(write), '-screen', '0', '1280x800x24',
                                       '-nolisten', 'tcp', '-noreset', '-ac'], pass_fds=(write,), stdout=log, stderr=log)
        os.close(write)
        assert select.select([read], [], [], 8)[0]
        display = ':' + os.read(read, 32).decode().strip()
        assert display[1:].isdigit()
        os.environ['DISPLAY'] = display
        call(['dbus-update-activation-environment', 'DISPLAY', 'XAUTHORITY'])
        with (root / 'kwin.log').open('w') as log:
            manager = subprocess.Popen(['kwin_x11', '--replace'], stdout=log, stderr=log)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            pid = subprocess.run(['qdbus6', 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                'org.freedesktop.DBus.GetConnectionUnixProcessID', 'org.kde.KWin'], capture_output=True, text=True)
            if pid.returncode == 0 and pid.stdout.strip() == str(manager.pid): break
            assert manager.poll() is None
            time.sleep(.1)
        else: raise AssertionError('Owned KWin not available')
        from PySide6.QtWidgets import QApplication, QLineEdit
        from PySide6.QtCore import QCoreApplication, QEvent
        from folego.core.custom_prompts import CustomPrompts
        from folego.ui.desktop_shortcuts import ShortcutTabs
        app = QApplication([])
        field = QLineEdit('123')
        field.setWindowTitle('Folego owned macro target')
        field.resize(450, 80); field.show()
        tabs = ShortcutTabs(); tabs.show()
        messages = []
        tabs.controller.result.connect(messages.append)
        def wait(predicate):
            end = time.monotonic() + 6
            while time.monotonic() < end:
                app.processEvents()
                if predicate(): return
                time.sleep(.02)
            raise AssertionError('Owned macro QA deadline')
        tabs.show_prompts()
        wait(lambda: tabs.custom_menu is not None and any(a.text() == 'Mostrar área de trabalho' for a in tabs.custom_menu.actions()))
        assert call(['qdbus6', 'org.kde.KWin', '/KWin', 'org.kde.KWin.showingDesktop']) == 'false'
        custom = tabs.custom_menu
        tabs.prompt_panel.footer_buttons['Custom'].click()
        wait(custom.isVisible)
        app.processEvents()
        action = next(a for a in custom.actions() if a.text() == 'Mostrar área de trabalho')
        point = custom.mapToGlobal(custom.actionGeometry(action).center())
        call(['xdotool', 'mousemove', str(point.x()), str(point.y()), 'click', '1'])
        try:
            wait(lambda: tabs.controller.future is None and call(['qdbus6', 'org.kde.KWin', '/KWin', 'org.kde.KWin.showingDesktop']) == 'true')
        except AssertionError:
            (root / 'failure.json').write_text(json.dumps(dict(action=tabs.controller.action, messages=messages,
                desktop=call(['qdbus6', 'org.kde.KWin', '/KWin', 'org.kde.KWin.showingDesktop'])), indent=2))
            raise
        assert field.isVisible()  # applications are preserved, not closed
        backend = tabs.controller.backend
        assert backend.show_desktop() == 'A área de trabalho já está visível'
        call(['qdbus6', 'org.kde.KWin', '/KWin', 'org.kde.KWin.showDesktop', 'false'])
        store = CustomPrompts(); snapshot = store.read()
        snapshot['entries'].append(dict(id='qa-select', kind='macro', title='Selecionar campo', action='keys', shortcut='Ctrl+A'))
        store.save(snapshot['entries'], snapshot['revision'])
        call(['xdotool', 'windowactivate', '--sync', str(int(field.winId()))])
        field.setFocus(); wait(field.hasFocus)
        tabs.show_prompts()
        wait(lambda: tabs.custom_menu is not None and any(a.text() == 'Selecionar campo' for a in tabs.custom_menu.actions()))
        custom = tabs.custom_menu
        tabs.prompt_panel.footer_buttons['Custom'].click()
        wait(custom.isVisible)
        action = next(a for a in custom.actions() if a.text() == 'Selecionar campo')
        point = custom.mapToGlobal(custom.actionGeometry(action).center())
        call(['xdotool', 'mousemove', str(point.x()), str(point.y()), 'click', '1'])
        wait(lambda: tabs.controller.future is None and field.selectedText() == '123')
        result = dict(passed=True, desktop_macro_from_menu=True, repeat_keeps_desktop_visible=True,
                      custom_key_macro=True, target_text_preserved=True,
                      scope='owned KWin/Xvfb and private D-Bus in PID/network namespaces; host runtime hidden')
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        tabs.shutdown(); field.close()
        for widget in list(app.topLevelWidgets()): widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()
    finally:
        if tabs is not None: tabs.shutdown()
        os.close(read)
        for child in (manager, server):
            if child is not None and child.poll() is None:
                child.terminate()  # exact test Popen children only
                child.wait(timeout=5)


if __name__ == '__main__':
    main()
