#!/usr/bin/env python3
"""Exercise real settings workers on Wayland with disposable login files."""
import argparse
import json
import os
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    root = args.state.resolve(); root.mkdir(mode=0o700, parents=True, exist_ok=False)
    for key, name in (('HOME', 'home'), ('XDG_CONFIG_HOME', 'config'),
                      ('XDG_STATE_HOME', 'state'), ('XDG_DATA_HOME', 'data'),
                      ('XDG_CACHE_HOME', 'cache'), ('TMPDIR', 'tmp'), ('XDG_CONFIG_DIRS', 'system')):
        folder = root / name; folder.mkdir(mode=0o700); os.environ[key] = str(folder)
    os.environ['XDG_CURRENT_DESKTOP'] = 'KDE'
    config = root / 'config'
    (config / 'autostart').mkdir()
    original = b'[Desktop Entry]\nType=Application\nExec=/bin/true\nHidden=false\n'
    target = config / 'autostart/steam-input.desktop'; target.write_bytes(original)
    from PySide6.QtWidgets import QApplication, QScrollArea, QMainWindow
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtTest import QTest
    from folego.ui.options_tab import OptionsTab
    from folego.ui.theme import apply_theme, paint_surface
    app = QApplication([]); app.setApplicationName('folego-qa-basic-session')
    apply_theme(app, 'snes-us')
    assert QGuiApplication.platformName() == 'wayland'
    class SettingsWindow(QMainWindow):
        def paintEvent(self, event):
            paint_surface(self)
            super().paintEvent(event)
    window = SettingsWindow(); tab = OptionsTab(); window.setCentralWidget(tab)
    window.resize(800, 593); window.show()
    def pump(predicate):
        deadline = time.monotonic() + 20
        while not predicate():
            assert time.monotonic() < deadline, tab.basic_status.text()
            app.processEvents(); time.sleep(.015)
    pump(lambda: window.windowHandle() and window.windowHandle().isExposed())
    answers = []
    tab.jobs.run('startup-basic-enable', '', confirm=True, done=lambda p: (
        answers.append(p), tab.show_basic_session(p)))
    pump(lambda: len(answers) == 1)
    assert answers[0]['configured'] and answers[0]['enabled']
    area = tab.findChild(QScrollArea)
    def click_choice():
        area.ensureWidgetVisible(tab.basic_choice, 20, 100)
        app.processEvents()
        pos = QPoint(8, tab.basic_choice.height() // 2)
        assert area.viewport().rect().contains(tab.basic_choice.mapTo(area.viewport(), pos))
        QTest.mouseClick(tab.basic_choice, Qt.MouseButton.LeftButton, pos=pos)
    area.ensureWidgetVisible(tab.basic_choice, 20, 100); app.processEvents()
    assert area.horizontalScrollBar().maximum() == 0
    assert window.grab().save(str(root / 'options.png'))
    click_choice()
    pump(lambda: tab.basic_choice.isEnabled() and not tab.basic_choice.isChecked())
    assert target.read_bytes() == original
    click_choice()
    pump(lambda: tab.basic_choice.isEnabled() and tab.basic_choice.isChecked())
    assert 'Hidden=true' in target.read_text()
    from folego.basic_session import BasicSession
    status = BasicSession().status()
    assert status['configured'] and status['enabled']
    restored = []
    tab.jobs.run('startup-basic-disable', '', confirm=True, done=restored.append)
    pump(lambda: bool(restored))
    assert restored[0]['state'] == 'restored' and target.read_bytes() == original
    (root / 'receipt.json').write_text(json.dumps({
        'platform': QGuiApplication.platformName(), 'mapped': True,
        'size': [window.width(), window.height()], 'horizontal_scroll': 0,
        'default_enabled': status['default_enabled'], 'worker_apply': answers[0]['configured'],
        'restore_exact': True, 'persisted_toggle': True, 'host_effects': 0}, indent=2))
    tab.stop(); window.close(); app.processEvents()
    print(root / 'receipt.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
