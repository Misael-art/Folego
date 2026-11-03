#!/usr/bin/env python3
"""Owned GUI QA: synthetic quotas, own keyboard surfaces and optional input.

Use a private X11 server for --input copy/paste: the physical session clipboard
is never a fixture. Wayland --input types only into this process's focused field.
No services, accounts, device preference, autostart or hardware repair is touched.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--input", action="store_true")
    parser.add_argument('--capture', action='store_true', help='Owned Spectacle lifecycle, cancel without saving')
    parser.add_argument('--reset-badges-only', action='store_true',
                        help='Synthetic tickets and blink lifecycle; no native input or capture tool')
    args = parser.parse_args()
    if args.input and not args.reset_badges_only and not args.offscreen and os.environ.get('XDG_SESSION_TYPE') == 'wayland':
        # Explicit native QA prepares only the product-owned keyboard rule in
        # the physical session, before isolating every account/data directory.
        from folego.adapters.keyboard_focus import ensure
        ensure(dict(os.environ), subprocess.run)
    root = args.state.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    for key, folder in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                        ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"),
                        ("XDG_CACHE_HOME", "cache"), ("TMPDIR", "tmp")):
        target = root / folder
        target.mkdir(mode=0o700)
        os.environ[key] = str(target)
    for key in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'GROK_HOME'):
        os.environ.pop(key, None)
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ['XDG_SESSION_TYPE'] = 'offscreen'
    from PySide6.QtCore import QTimer, QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit, QLabel, QMenu
    from folego.core import ai_sessions as ai
    from folego.core.snapshot import MemInfo, Snapshot
    from folego.core.tmpfs import TmpfsVolume
    from folego.ui.compact import CompactWindow
    from folego.ui.desktop_caps import detect
    from folego.ui.theme import apply_theme
    from folego.ui.title_signal import TitleSignal
    from folego.ui.custom_prompts_tab import CustomPromptsTab

    app = QApplication([])
    app.setApplicationName('folego')
    app.setDesktopFileName('folego')
    apply_theme(app)
    target = QLineEdit()
    target.setWindowTitle("Fôlego QA — campo próprio")
    target.resize(450, 80)
    target.show()
    editor = CustomPromptsTab()
    editor.setWindowTitle('Fôlego QA — textos e macros próprios')
    editor.resize(760, 470)
    class Host:
        raised = 0
        paused = False
        def raise_to_user(self):
            self.raised += 1
        def toggle_pause(self):
            self.paused = not self.paused
            return self.paused
        def quit(self):
            app.quit()
        def open_custom_prompts(self):
            editor.show()
    class Store:
        def value(self, key, default=None):
            from folego.ui.desktop_preferences import enabled, SHOW_IN_CAPTURE
            return enabled(key) if key == SHOW_IN_CAPTURE else default
        def setValue(self, key, value): pass
        def sync(self): pass
    host = Host()
    view = CompactWindow(host, caps=detect(session_type=os.environ.get("XDG_SESSION_TYPE"),
                                          platform=app.platformName()), store=Store())
    now = time.time()
    items = [ai.unknown(p) for p in ai.NAMES]
    for item, used in ((items[0], 72), (items[2], 18)):
        item.update(observed_at=now, windows=[ai.quota_window("Sessão", used, now + 3600, now)])
    for item in items:
        item.update(account_id=item['provider'] + '-principal', label='Principal', default=True)
    other = ai.unknown('codex', label='Trabalho · projetos')
    other.update(account_id='codex-work', default=False, observed_at=now,
                 windows=[ai.quota_window('Sessão (5 h)', 92, now + 600, now),
                          ai.quota_window('Semana', 48, now + 86400, now)])
    items.append(other)
    items[0]['windows'].append(ai.quota_window('Semana', 43, now + 86400, now))
    items[0].update(reset_credits=dict(available=2, observed_at=now, expires_at=now + 86400),
                    extra_credits='9.99', billing_day=15, billing_source='referência de demonstração')
    view.ai_strip.poller._collect = lambda: items
    if args.reset_badges_only:
        delivery_rows = [dict(provider=p, count=n, pending=[], complete=True)
                         for p, n in zip(ai.NAMES, (3, 1, 5, 2))]
        view.ai_strip.delivery_poller._collect = lambda: delivery_rows
        view.ai_strip.set_deliveries(delivery_rows)
        for item, count in zip(items, (2, 1, 3, 1, 1)):
            item['reset_credits'] = dict(available=count, observed_at=now, expires_at=now + 3600)
    sample = Snapshot(ts=now, mono=time.monotonic(), mem=MemInfo(16 * 1024**2, 6 * 1024**2),
                      swap_used_kb=1024, swap_total_kb=8192, pressure_memory=None, pressure_io=None,
                      pressure_cpu=None, load=None, apps=(), self_rss_kb=0, cpu_busy_frac=.24,
                      tmpfs=(TmpfsVolume("/qa/runtime", "tmpfs", 100, 81, 19, is_runtime=True),))
    view.show_snapshot(sample, signal=TitleSignal("yellow", "🟡", "Fôlego · atenção"))
    view.show_compact()
    app.processEvents()
    view.ai_strip.set_items(items)
    records = []
    external = None
    def wait(predicate, seconds=8):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            if predicate(): return
            time.sleep(.02)
        raise AssertionError("QA deadline")
    def pointer_click(button, click=True):
        if os.environ.get('XDG_SESSION_TYPE') != 'wayland':
            point = button.mapToGlobal(button.rect().center())
            subprocess.run(['xdotool', 'mousemove', str(point.x()), str(point.y()), 'click', '1'], check=True)
            return
        import re
        backend = view.shortcut_tabs.controller.backend
        binary, _ = backend._input()
        app.processEvents()
        point = button.mapToGlobal(button.rect().center())
        desired = (point.x(), point.y())
        if args.reset_badges_only:
            # Wayland QWidget globals may differ from compositor coordinates.
            own = subprocess.check_output(['kdotool', 'search', '--all', '--pid', str(os.getpid()),
                                          '--name', '^Fôlego — widget$'], text=True).strip().splitlines()
            assert len(own) == 1
            native = subprocess.check_output(['kdotool', 'getwindowgeometry', own[0]], text=True)
            position = re.search(r'Position:\s*([-0-9.]+),([-0-9.]+)', native)
            assert position
            origin = view.mapToGlobal(view.rect().topLeft())
            desired = (float(position[1]) + point.x() - origin.x(),
                       float(position[2]) + point.y() - origin.y())
            subprocess.run(['kdotool', 'windowraise', own[0]], check=True, capture_output=True)
        if not click:
            # A pointer already at the new surface's centre still needs a real
            # motion event to start Qt's hover timer after mapping/raising it.
            subprocess.run([binary, 'mousemove', '--', '4', '0'], env=backend.env, check=True, capture_output=True)
            app.processEvents()
        def cursor():
            raw = subprocess.check_output(['kdotool', 'getmouselocation'], text=True).strip()
            match = re.search(r'x[:=]\s*([-0-9.]+).*y[:=]\s*([-0-9.]+)', raw)
            assert match, raw
            return float(match[1]), float(match[2])
        factors = [view.devicePixelRatioF()] * 2
        for _ in range(12):
            current = cursor()
            delta = [desired[i] - current[i] for i in range(2)]
            if max(map(abs, delta)) <= 1: break
            amounts = [round(delta[i] * factors[i]) for i in range(2)]
            subprocess.run([binary, 'mousemove', '--', *(str(n) for n in amounts)],
                           env=backend.env, check=True, capture_output=True)
            time.sleep(.06)
            app.processEvents()
            after = cursor()
            for i in range(2):
                actual = after[i] - current[i]
                if abs(actual) > 1 and amounts[i]:
                    factors[i] = max(.2, min(4, abs(amounts[i] / actual)))
        assert max(abs(cursor()[i] - desired[i]) for i in range(2)) <= 1, 'pointer unconfirmed; click blocked'
        native = subprocess.check_output(['kdotool', 'getmouselocation'], text=True).strip()
        surface = re.search(r'window[:=]\s*(\{[0-9a-fA-F-]+\})', native)
        assert surface is not None, 'pointer surface unknown; click blocked'
        owner = subprocess.check_output(['kdotool', 'getwindowpid', surface[1]], text=True).strip()
        assert owner == str(os.getpid()), 'pointer is outside the owned QA process; click blocked'
        if click:
            title = subprocess.check_output(['kdotool', 'getwindowname', surface[1]], text=True).strip()
            assert title == button.window().windowTitle(), 'pointer is outside the intended QA surface; click blocked'
            subprocess.run([binary, 'click', '0xC0'], env=backend.env, check=True, capture_output=True)
    try:
        wait(lambda: view.isVisible())
        if args.reset_badges_only:
            strip = view.ai_strip
            wait(lambda: view.windowHandle().isExposed())
            if app.platformName() == 'wayland':
                native = []
                def own_widget():
                    result = subprocess.run(['kdotool', 'search', '--all', '--pid', str(os.getpid()),
                                             '--name', '^Fôlego — widget$'], capture_output=True, text=True, timeout=3)
                    native[:] = result.stdout.strip().splitlines()
                    return len(native) == 1
                wait(own_widget)
                geometry = subprocess.check_output(['kdotool', 'getwindowgeometry', native[0]], text=True)
            else:
                geometry = 'offscreen; no compositor proof'
            assert view.width() == 280 and strip.reset_blink.isActive()
            view.adjustSize()
            wait(lambda: all(b.parentWidget().rect().contains(b.geometry())
                             for b in strip.reset_badges.values()))
            for provider, total in zip(ai.NAMES, (3, 1, 3, 1)):
                gift, delivery = strip.reset_badges[provider], strip.badges[provider]
                assert gift.isVisible() and gift.text() == str(total)
                assert gift.geometry().left() > delivery.geometry().right()
                assert gift.parentWidget().rect().contains(gift.geometry())
                assert strip.rect().contains(gift.mapTo(strip, gift.rect().bottomRight()))
            records.append(dict(gifts='four providers, confirmed multi-account counts, beside deliveries',
                                logical_width=view.width(), native_geometry=geometry))
            wait(lambda: strip._reset_bright)
            view.grab().save(str(root / 'compact-gifts-bright.png'))
            wait(lambda: not strip._reset_bright)
            assert strip.reset_badges['codex'].graphicsEffect().opacity() == .5
            view.grab().save(str(root / 'compact-gifts-dim.png'))
            wait(lambda: strip._reset_bright)
            assert strip.reset_badges['codex'].graphicsEffect().opacity() == 1
            records.append(dict(blink='real QTimer bright/dim/bright; count never disappears', interval_ms=800))
            view.hide(); app.processEvents()
            assert not strip.reset_blink.isActive()
            view.show_compact(); app.processEvents()
            wait(lambda: view.windowHandle().isExposed() and strip.reset_blink.isActive())
            records.append(dict(lifecycle='hidden stops timer; return resumes'))
            # Only the secondary account contributes now; gift must lead there.
            items[0]['reset_credits']['available'] = 0
            strip.set_items(items)
            assert strip.reset_badges['codex'].text() == '1'
            if args.input:
                pointer_click(strip.reset_badges['codex'])
            else:
                strip.reset_badges['codex'].click()
            wait(lambda: strip.account_panel is not None and strip.account_menu.isVisible())
            assert strip.account_panel.selected == 'codex-work'
            settled = time.monotonic() + .35
            wait(lambda: time.monotonic() >= settled)
            # This harness pumps processEvents instead of app.exec; flush Qt's
            # deferred disposal of the previous account before inspecting pixels.
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
            labels = [label.text() for label in strip.account_panel.findChildren(QLabel) if label.isVisible()]
            assert 'Tickets de reset · 1 disponíveis' in labels and '92% usado' in labels
            assert 'Tickets de reset · 0 disponíveis' not in labels and '72% usado' not in labels
            strip.account_panel.grab().save(str(root / 'reset-account.png'))
            strip.account_menu.close(); app.processEvents()
            records.append(dict(account='gift selects secondary account with ticket; no redemption'))
            for item in items:
                item['reset_credits']['expires_at'] = now - 1
            strip.render()
            assert all(b.isHidden() for b in strip.reset_badges.values()) and not strip.reset_blink.isActive()
            assert strip.badges['codex'].text() == '3'
            for item in items:
                item['reset_credits'].update(expires_at=now + 3600, available=0)
            strip.render()
            assert all(b.isHidden() for b in strip.reset_badges.values()) and not strip.reset_blink.isActive()
            records.append(dict(invalidation='expiry and zero hide gifts, stop timer, preserve deliveries'))
            (root / 'result.json').write_text(json.dumps(dict(platform=app.platformName(),
                size=[view.width(), view.height()], cases=records, passed=True), indent=2) + '\n')
            print(json.dumps(dict(passed=True, state=str(root), cases=len(records))))
            return
        if args.input and os.environ.get('XDG_SESSION_TYPE') == 'wayland':
            native_windows = []
            def mapped_widget():
                result = subprocess.run(['kdotool', 'search', '--all', '--pid', str(os.getpid()),
                                         '--name', '^Fôlego — widget$'], capture_output=True, text=True, timeout=3)
                native_windows[:] = result.stdout.strip().splitlines()
                return len(native_windows) == 1
            wait(mapped_widget)
            view.move(20, 130)
            own = root / 'place-owned-widget.js'
            own.write_text('const w=workspace.windowList().find(w=>w.pid==='+str(os.getpid())+' && w.caption==="Fôlego — widget");if(w) w.frameGeometry={x:20,y:130,width:280,height:'+str(view.height())+'};')
            name = 'folego-qa-widget-'+str(os.getpid())
            sid = subprocess.check_output(['qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.loadScript',str(own),name],text=True).strip()
            try:
                subprocess.run(['qdbus6','org.kde.KWin','/Scripting/Script'+sid,'org.kde.kwin.Script.run'],check=True,capture_output=True)
                def placement_confirmed():
                    import re
                    result = subprocess.run(['kdotool', 'getwindowgeometry', native_windows[0]],
                                            capture_output=True, text=True, timeout=3)
                    position = re.search(r'Position:\s*([-0-9.]+),([-0-9.]+)', result.stdout)
                    return position is not None and abs(float(position[1])-20)<=1 and abs(float(position[2])-130)<=1
                wait(placement_confirmed)
                subprocess.run(['kdotool', 'windowraise', native_windows[0]], check=True, capture_output=True)
            finally:
                subprocess.run(['qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.unloadScript',name],check=True,capture_output=True)
        view.adjustSize()
        from PySide6.QtCore import Qt, QEvent, QPoint
        from PySide6.QtGui import QHelpEvent
        assert view.testAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        button = view.ai_strip.buttons['codex']
        if args.input and os.environ.get('XDG_SESSION_TYPE') == 'wayland':
            pointer_click(button, click=False)
        help_event = QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), button.mapToGlobal(QPoint(5, 5)))
        if not (args.input and os.environ.get('XDG_SESSION_TYPE') == 'wayland'):
            app.sendEvent(button, help_event)
        wait(lambda: view.ai_strip.account_panel is not None and view.ai_strip.account_menu.isVisible())
        # Allow the mapped Wayland popup to receive its fractional output scale.
        settle = time.monotonic() + .3
        while time.monotonic() < settle:
            app.processEvents()
            time.sleep(.01)
        panel = view.ai_strip.account_panel
        assert panel.selected == 'codex-principal'
        assert any('2 disponíveis' in w.text() for w in panel.findChildren(QLabel))
        assert any('Assinatura · dia 15' in w.text() for w in panel.findChildren(QLabel))
        panel.grab().save(str(root / 'accounts-default.png'))
        panel.account_buttons['codex-work'].click()
        app.processEvents()
        assert panel.selected == 'codex-work'
        assert any(w.text() == '92% usado' for w in panel.findChildren(QLabel))
        panel.grab().save(str(root / 'accounts-other.png'))
        records.append(dict(accounts='interactive default and secondary card', fields=['quota', '5h', 'weekly', 'tickets', 'monthly']))
        view.ai_strip.account_menu.close()
        app.processEvents()
        view.shortcut_tabs.buttons['prompts'].click()
        wait(lambda: any(m.isVisible() for m in view.findChildren(QMenu)))
        menus = [m for m in view.findChildren(QMenu) if m.isVisible()]
        assert len(view.shortcut_tabs.prompt_panel.buttons) == 12
        menus[-1].grab().save(str(root / 'prompts.png'))
        tabs = view.shortcut_tabs
        wait(lambda: tabs.custom_menu is not None and any(a.text() == '123' for a in tabs.custom_menu.actions()))
        assert list(tabs.prompt_panel.footer_buttons)[-1] == 'Custom'
        custom = tabs.custom_menu
        tabs.prompt_panel.footer_buttons['Custom'].click()
        app.processEvents()
        custom.grab().save(str(root / 'custom-menu.png'))
        next(a for a in custom.actions() if a.text() == 'Editar textos e macros…').trigger()
        assert tabs.prompt_menu is None
        wait(lambda: editor.isVisible() and editor.readable and not editor.busy)
        assert editor.text.toPlainText() == '123'
        editor.grab().save(str(root / 'custom-editor.png'))
        editor.add_text.click()
        editor.title.setText('Texto de QA')
        editor.text.setPlainText('Texto personalizado\n123')
        editor.save.click()
        wait(lambda: not editor.busy and len(editor.entries) == 3)
        editor.add_macro.click()
        editor.title.setText('Atalho de QA')
        editor.action.setCurrentIndex(1)
        editor.shortcut.setText('Ctrl+Alt+T')
        editor.save.click()
        wait(lambda: not editor.busy and len(editor.entries) == 4)
        editor.grab().save(str(root / 'custom-macro-editor.png'))
        editor.shutdown()
        editor.close()
        view.show_compact()
        records.append(dict(custom='last submenu, literal 123, standard editor and saved text/macro without execution'))
        records.append(dict(prompts='menu titles available; no physical clipboard fixture'))
        view.grab().save(str(root / "compact.png"))
        assert view.width() == 280
        for button in view.shortcut_tabs.buttons.values():
            assert button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 2
        view.pause_button.click()
        assert host.paused
        view.pause_button.click()
        assert not host.paused
        for position in ("bottom", "top", "bottom"):
            if position == "top": view.shortcut_tabs.top_button.click()
            else: view.shortcut_tabs.buttons["keyboard"].click()
            keyboard = view.shortcut_tabs.keyboard
            wait(lambda: keyboard.isVisible())
            if not args.offscreen and os.environ.get("XDG_SESSION_TYPE") == "wayland":
                wait(lambda: keyboard.confirmed_geometry == keyboard._geometry)
            elif os.environ.get("XDG_SESSION_TYPE") == "x11":
                wait(lambda: keyboard.geometry().getRect() == keyboard._geometry)
            records.append(dict(position=position, requested=keyboard._geometry,
                                confirmed=keyboard.confirmed_geometry, visible=keyboard.isVisible()))
            keyboard.grab().save(str(root / ("keyboard-" + position + ".png")))
        if args.input:
            assert not args.offscreen
            if os.environ.get("XDG_SESSION_TYPE") == "wayland":
                script = root / "focus-owned.js"
                script.write_text("const w=workspace.windowList().find(w=>w.pid===" + str(os.getpid())
                                  + ' && w.caption==="Fôlego QA — campo próprio"); if(w) workspace.activeWindow=w;')
                name = "folego-qa-focus-" + str(os.getpid())
                result = subprocess.check_output(["qdbus6", "org.kde.KWin", "/Scripting",
                             "org.kde.kwin.Scripting.loadScript", str(script), name], text=True).strip()
                try:
                    subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting/Script" + result,
                                    "org.kde.kwin.Script.run"], check=True)
                finally:
                    subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                                    "org.kde.kwin.Scripting.unloadScript", name], check=True)
            else:
                # An explicit private display is mandatory before writing a clipboard.
                assert os.environ.get("FOLEGO_QA_PRIVATE_DISPLAY") == os.environ.get("DISPLAY")
                subprocess.run(["xdotool", "windowfocus", str(int(target.winId()))], check=True)
            target.setFocus()
            wait(lambda: target.isActiveWindow() and target.hasFocus())
            controller = view.shortcut_tabs.controller
            wait(lambda: controller.future is None)
            pointer_click(next(b for b in keyboard.letters if b.text() == 'A'))
            wait(lambda: controller.future is None)
            wait(lambda: target.text() == "a", seconds=3)
            assert target.hasFocus() and not keyboard.isActiveWindow()
            pointer_click(next(b for b in keyboard.letters if b.text() == 'B'))
            wait(lambda: target.text() == 'ab', seconds=3)
            assert target.hasFocus()
            records.append({"input": "real pointer clicks A/B into owned focused field; keyboard stayed inactive"})
            wait(lambda: controller.future is None)
            target.setText('Texto de QA com acentos')
            view.shortcut_tabs.buttons['select_all'].click()
            wait(lambda: controller.future is None)
            wait(lambda: target.selectedText() == 'Texto de QA com acentos', seconds=3)
            assert target.hasFocus()
            view.shortcut_tabs.buttons['delete_all'].click()
            wait(lambda: controller.future is None)
            wait(lambda: target.text() == '', seconds=3)
            records.append(dict(editing='native AT-SPI select/delete only the owned focused field'))
            if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
                caption = 'Fôlego QA — editor externo ' + str(os.getpid())
                external = subprocess.Popen([sys.executable, str(Path(__file__).with_name('qa_text_target.py')),
                                             '--caption', caption], env=dict(os.environ),
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                service = 'org.folego.QAText.p' + str(external.pid)
                def remote(method):
                    return subprocess.run(['qdbus6', service, '/target', 'org.folego.QAText.' + method],
                                          capture_output=True, text=True, timeout=3)
                wait(lambda: remote('value').returncode == 0)
                def focus_external():
                    script = root / 'focus-external.js'
                    script.write_text('const w=workspace.windowList().find(w=>w.pid==='+str(external.pid)+
                                      ' && w.caption==='+json.dumps(caption)+');if(w){w.frameGeometry={x:340,y:380,width:440,height:140};workspace.activeWindow=w;}')
                    name = 'folego-qa-external-' + str(os.getpid())
                    sid = subprocess.check_output(['qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.loadScript',str(script),name],text=True).strip()
                    try:
                        subprocess.run(['qdbus6','org.kde.KWin','/Scripting/Script'+sid,'org.kde.kwin.Script.run'],check=True,capture_output=True)
                    finally:
                        subprocess.run(['qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.unloadScript',name],check=True,capture_output=True)
                    assert remote('focus').returncode == 0
                    def active_owned():
                        active = subprocess.check_output(['kdotool','getactivewindow'], text=True).strip()
                        return subprocess.check_output(['kdotool','getwindowpid',active],text=True).strip() == str(external.pid)
                    wait(active_owned)
                view.shortcut_tabs.top_button.click()
                wait(lambda: keyboard.confirmed_geometry == keyboard._geometry and controller.future is None)
                focus_external()
                pointer_click(next(b for b in keyboard.letters if b.text() == 'C'))
                wait(lambda: remote('value').stdout.strip() == 'c')
                assert not keyboard.isActiveWindow()
                pointer_click(next(b for b in keyboard.findChildren(type(button)) if b.text() == 'Shift'))
                pointer_click(next(b for b in keyboard.letters if b.text() == 'D'))
                wait(lambda: remote('value').stdout.strip() == 'cD')
                pointer_click(next(b for b in keyboard.findChildren(type(button)) if b.text() == 'Apagar'))
                wait(lambda: remote('value').stdout.strip() == 'c')
                assert remote('quit').returncode == 0
                external.wait(timeout=5)
                external = None
                records.append(dict(external_input='real pointer C, Shift+D and backspace into owned separate process; top keyboard retained external focus'))
            if os.environ.get("XDG_SESSION_TYPE") == "x11":
                from folego.core.development_prompts import text
                view.shortcut_tabs.copy_prompt('diagnose')
                assert app.clipboard().text() == text('diagnose')
                target.setText("Folego QA")
                target.selectAll()
                controller.request("copy")
                wait(lambda: controller.future is None)
                target.clear()
                controller.request("paste")
                wait(lambda: controller.future is None)
                assert target.text() == "Folego QA"
                records.append({"clipboard": "copy/paste in private X server"})
        if args.capture:
            assert args.input and os.environ.get('XDG_SESSION_TYPE') == 'wayland'
            from folego.ui.options_tab import OptionsTab
            from folego.core.agent_deliveries import identity
            class Jobs:
                def run(self, *args, **kwargs): pass
                def shutdown(self): pass
            preferences = OptionsTab(jobs=Jobs())
            preferences.resize(730, 510); preferences.show(); app.processEvents()
            assert preferences.capture_choice.isChecked() and preferences.sound_kind.count() == 7
            preferences.grab().save(str(root / 'capture-sound-options.png'))
            if view.shortcut_tabs.keyboard is not None: view.shortcut_tabs.keyboard.hide()
            backend = view.shortcut_tabs.controller.backend
            for include in (True, False):
                preferences.show()
                if preferences.capture_choice.isChecked() != include: preferences.capture_choice.click()
                preferences.hide(); view.show_compact(); app.processEvents()
                wait(lambda: view.isVisible() and view.shortcut_tabs.controller.future is None)
                if not include:
                    view.shortcut_tabs.keyboard.show_at('top', view.screen())
                    wait(lambda: view.shortcut_tabs.keyboard.confirmed_geometry is not None and view.shortcut_tabs.controller.future is None)
                place = root / 'place-capture-widget.js'
                place.write_text('const w=workspace.windowList().find(w=>w.pid==='+str(os.getpid())+' && w.caption==="Fôlego — widget");if(w){w.keepAbove=true;w.frameGeometry={x:20,y:130,width:280,height:'+str(view.height())+'};}')
                name='folego-qa-capture-'+str(os.getpid())
                sid=subprocess.check_output(['qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.loadScript',str(place),name],text=True).strip()
                try:
                    subprocess.run(['qdbus6','org.kde.KWin','/Scripting/Script'+sid,'org.kde.kwin.Script.run'],check=True,capture_output=True)
                    wait(lambda: abs(view.x()-20)<=1 and abs(view.y()-130)<=1 and view.windowHandle().isExposed())
                finally:
                    subprocess.run(['qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.unloadScript',name],check=True,capture_output=True)
                pointer_click(view.shortcut_tabs.buttons['print'])
                wait(lambda: backend.capture is not None and backend.capture.poll() is None)
                capture = backend.capture; owner = identity(capture.pid); assert owner is not None
                def capture_active():
                    result = subprocess.run(['kdotool','getactivewindow'],capture_output=True,text=True)
                    if result.returncode: return False
                    result = subprocess.run(['kdotool','getwindowpid',result.stdout.strip()],capture_output=True,text=True)
                    return result.returncode == 0 and result.stdout.strip() == str(capture.pid)
                wait(capture_active)
                assert view.isVisible() == include
                if not include:
                    assert not view.windowHandle().isExposed()
                    native = subprocess.run(['kdotool','search','--all','--pid',str(os.getpid()),'--name','^Fôlego — widget$'],capture_output=True,text=True)
                    assert not native.stdout.strip(), 'Hidden widget is still mapped in compositor'
                assert capture_active() and identity(capture.pid) == owner
                backend.keys([1])  # Escape only to the exact owned capture child
                wait(lambda: capture.poll() is not None and view.isVisible() and not view._capture_waiting)
                if not include:
                    wait(lambda: view.shortcut_tabs.controller.action == 'capture-place' and view.shortcut_tabs.controller.future is None)
                    assert abs(view.x()-20)<=1 and abs(view.y()-130)<=1
                    wait(lambda: view.shortcut_tabs.keyboard.isVisible() and view.shortcut_tabs.keyboard.confirmed_geometry is not None and view.shortcut_tabs.controller.future is None)
                else: wait(lambda: view.shortcut_tabs.controller.future is None)
                records.append(dict(capture_include_widget=include, native_tool_closed=True, widget_restored=True, region_saved=False))
            preferences.stop(); preferences.close()
        view.open_button.click()
        assert host.raised == 1 and not view.isVisible()
        view.force_close()
        editor.shutdown()
        editor.close()
        backend = view.shortcut_tabs.controller.backend
        wait(lambda: backend.daemon is None)
        target.close()
        (root / "result.json").write_text(json.dumps({"platform": app.platformName(),
              "size": [view.width(), view.height()], "cases": records, "passed": True}, indent=2) + "\n")
        print(json.dumps({"passed": True, "state": str(root), "cases": len(records)}))
    except Exception:
        view.grab().save(str(root / 'failure.png'))
        keyboard = view.shortcut_tabs.keyboard
        (root / "failure.json").write_text(json.dumps({"status": keyboard.status.text() if keyboard else None,
            "observed": keyboard.observed_geometry if keyboard else None,
            "requested": keyboard._geometry if keyboard else None,
            "feedback": view.feedback_label.text(),
            "badges": {p: dict(row=b.parentWidget().rect().getRect(), gift=b.geometry().getRect())
                       for p, b in view.ai_strip.reset_badges.items()}}, indent=2))
        raise
    finally:
        capture = view.shortcut_tabs.controller.backend.capture
        if capture is not None and capture.poll() is None:
            capture.terminate(); capture.wait(timeout=5)  # exact QA-created Popen only
        editor.shutdown()
        editor.close()
        if external is not None:
            subprocess.run(['qdbus6', 'org.folego.QAText.p' + str(external.pid), '/target',
                            'org.folego.QAText.quit'], capture_output=True, timeout=3)
            try: external.wait(timeout=5)
            except subprocess.TimeoutExpired:
                external.terminate()  # exact disposable Popen child only
                external.wait(timeout=5)
        view.force_close()
        target.close()
        for window in list(app.topLevelWidgets()):
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


if __name__ == "__main__":
    main()
