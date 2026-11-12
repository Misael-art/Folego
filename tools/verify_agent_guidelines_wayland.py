#!/usr/bin/env python3
"""Exercise the actual care checkbox and CLI workers in a disposable Wayland window."""
import argparse
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    root = args.state.resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    for key, name in (('HOME', 'home'), ('XDG_CONFIG_HOME', 'config'),
                      ('XDG_STATE_HOME', 'state'), ('XDG_DATA_HOME', 'data'),
                      ('XDG_CACHE_HOME', 'cache'), ('TMPDIR', 'tmp')):
        folder = root / name; folder.mkdir(mode=0o700); os.environ[key] = str(folder)
    home = root / 'home'
    target = home / '.codex/AGENTS.md'
    target.parent.mkdir()
    (home / '.claude').mkdir()
    original = b'# Personal instructions\n@RTK.md\n'
    target.write_bytes(original); target.chmod(0o640)
    from PySide6.QtWidgets import QApplication, QMainWindow, QScrollArea
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from folego.ui.options_tab import OptionsTab
    from folego.ui.theme import apply_theme, paint_surface
    from folego.actions.agent_guidelines import BLOCK, AgentGuidelines
    app = QApplication([]); app.setApplicationName('folego-qa-agent-care')
    apply_theme(app, 'snes-us')
    assert QGuiApplication.platformName() == 'wayland'
    class Window(QMainWindow):
        def paintEvent(self, event):
            paint_surface(self)
            super().paintEvent(event)
    window = Window(); tab = OptionsTab(); window.setCentralWidget(tab)
    window.resize(800, 590); window.show()
    def pump(predicate):
        end = time.monotonic() + 25
        while not predicate():
            assert time.monotonic() < end, tab.care_status.text()
            app.processEvents(); time.sleep(.015)
    pump(lambda: window.windowHandle() and window.windowHandle().isExposed())
    def click():
        area = tab.findChild(QScrollArea)
        area.ensureWidgetVisible(tab.care_choice, 20, 90)
        app.processEvents()
        pos = QPoint(8, tab.care_choice.height() // 2)
        def visible():
            area.ensureWidgetVisible(tab.care_choice, 20, 90)
            return area.viewport().rect().contains(tab.care_choice.mapTo(area.viewport(), pos))
        pump(visible)  # Wait for the mapped window's final scroll geometry.
        QTest.mouseClick(tab.care_choice, Qt.MouseButton.LeftButton, pos=pos)
    assert not tab.care_choice.isChecked()
    click()
    pump(lambda: tab.care_choice.isEnabled() and AgentGuidelines().status()['managed'] == 2)
    assert target.read_bytes().startswith(original) and target.read_bytes().count(BLOCK) == 1
    assert tab._care_timer.isActive()
    new = home / '.prime/agent'; new.mkdir(parents=True)
    tab.sync_agent_care()
    pump(lambda: (new / 'AGENTS.md').exists() and not tab._care_poller._inflight)
    extra = b'\n# Later personal addition\n'
    target.write_bytes(target.read_bytes() + extra)
    area = tab.findChild(QScrollArea)
    assert area.horizontalScrollBar().maximum() == 0
    assert window.grab().save(str(root / 'options.png'))
    click()
    pump(lambda: tab.care_choice.isEnabled() and not tab.care_choice.isChecked())
    assert target.read_bytes() == original + extra
    assert not (new / 'AGENTS.md').exists() and not (home / '.claude/CLAUDE.md').exists()
    assert target.stat().st_mode & 0o777 == 0o640
    assert not AgentGuidelines().preference() and not tab._care_timer.isActive()
    (root / 'receipt.json').write_text(json.dumps({
        'platform': QGuiApplication.platformName(), 'mapped': True,
        'size': [window.width(), window.height()], 'horizontal_scroll': 0,
        'worker_apply': True, 'discovery_of_new_client': True,
        'preserved_later_edits_and_mode': True, 'restored_created_files': True,
        'disabled_preference_persisted': True, 'timer_stopped': True,
        'host_agent_files_modified': 0}, indent=2))
    tab.stop(); window.close(); app.processEvents()
    print(root / 'receipt.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
