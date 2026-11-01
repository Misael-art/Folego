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
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--input", action="store_true")
    args = parser.parse_args()
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
    from PySide6.QtCore import QTimer, QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QLineEdit, QToolTip
    from folego.core import ai_sessions as ai
    from folego.core.snapshot import MemInfo, Snapshot
    from folego.core.tmpfs import TmpfsVolume
    from folego.ui.compact import CompactWindow
    from folego.ui.desktop_caps import detect
    from folego.ui.theme import apply_theme
    from folego.ui.title_signal import TitleSignal

    app = QApplication([])
    app.setApplicationName('folego-owned-qa')
    apply_theme(app)
    target = QLineEdit()
    target.setWindowTitle("Fôlego QA — campo próprio")
    target.resize(450, 80)
    target.show()
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
    class Store:
        def value(self, key, default=None): return default
        def setValue(self, key, value): pass
        def sync(self): pass
    host = Host()
    view = CompactWindow(host, caps=detect(session_type=os.environ.get("XDG_SESSION_TYPE"),
                                          platform=app.platformName()), store=Store())
    now = time.time()
    items = [ai.unknown(p) for p in ai.NAMES]
    for item, used in ((items[0], 72), (items[2], 18)):
        item.update(observed_at=now, windows=[ai.quota_window("Sessão", used, now + 3600, now)])
    items[0].update(reset_credits=dict(available=2, observed_at=now, expires_at=now + 86400),
                    extra_credits='9.99', billing_day=15, billing_source='referência de demonstração')
    view.ai_strip.poller._collect = lambda: items
    sample = Snapshot(ts=now, mono=time.monotonic(), mem=MemInfo(16 * 1024**2, 6 * 1024**2),
                      swap_used_kb=1024, swap_total_kb=8192, pressure_memory=None, pressure_io=None,
                      pressure_cpu=None, load=None, apps=(), self_rss_kb=0, cpu_busy_frac=.24,
                      tmpfs=(TmpfsVolume("/qa/runtime", "tmpfs", 100, 81, 19, is_runtime=True),))
    view.show_snapshot(sample, signal=TitleSignal("yellow", "🟡", "Fôlego · atenção"))
    view.show_compact()
    app.processEvents()
    view.ai_strip.set_items(items)
    records = []
    def wait(predicate, seconds=8):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            if predicate(): return
            time.sleep(.02)
        raise AssertionError("QA deadline")
    try:
        wait(lambda: view.isVisible())
        view.adjustSize()
        from PySide6.QtCore import Qt, QEvent, QPoint
        from PySide6.QtGui import QHelpEvent
        assert view.testAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        button = view.ai_strip.buttons['codex']
        help_event = QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), button.mapToGlobal(QPoint(5, 5)))
        app.sendEvent(button, help_event)
        wait(lambda: QToolTip.isVisible())
        assert 'Tickets de reposição: 2' in QToolTip.text() and 'Renovação mensal' in QToolTip.text()
        records.append(dict(tooltip='Qt help event in non-focusing widget', fields=['quota', 'reset', 'tickets', 'monthly']))
        QToolTip.hideText()
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
            controller.request("key", [30])
            wait(lambda: controller.future is None)
            wait(lambda: target.text() == "a", seconds=3)
            records.append({"input": "native key into owned focused field"})
            target.setText('Texto de QA com acentos')
            view.shortcut_tabs.buttons['select_all'].click()
            wait(lambda: controller.future is None)
            wait(lambda: target.selectedText() == 'Texto de QA com acentos', seconds=3)
            assert target.hasFocus()
            view.shortcut_tabs.buttons['delete_all'].click()
            wait(lambda: controller.future is None)
            wait(lambda: target.text() == '', seconds=3)
            records.append(dict(editing='native AT-SPI select/delete only the owned focused field'))
            if os.environ.get("XDG_SESSION_TYPE") == "x11":
                target.setText("Folego QA")
                target.selectAll()
                controller.request("copy")
                wait(lambda: controller.future is None)
                target.clear()
                controller.request("paste")
                wait(lambda: controller.future is None)
                assert target.text() == "Folego QA"
                records.append({"clipboard": "copy/paste in private X server"})
        view.open_button.click()
        assert host.raised == 1 and not view.isVisible()
        view.force_close()
        backend = view.shortcut_tabs.controller.backend
        wait(lambda: backend.daemon is None)
        target.close()
        (root / "result.json").write_text(json.dumps({"platform": app.platformName(),
              "size": [view.width(), view.height()], "cases": records, "passed": True}, indent=2) + "\n")
        print(json.dumps({"passed": True, "state": str(root), "cases": len(records)}))
    except Exception:
        keyboard = view.shortcut_tabs.keyboard
        (root / "failure.json").write_text(json.dumps({"status": keyboard.status.text() if keyboard else None,
            "observed": keyboard.observed_geometry if keyboard else None,
            "requested": keyboard._geometry if keyboard else None,
            "feedback": view.feedback_label.text()}, indent=2))
        raise
    finally:
        view.force_close()
        target.close()
        for window in list(app.topLevelWidgets()):
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


if __name__ == "__main__":
    main()
