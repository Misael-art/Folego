#!/usr/bin/env python3
"""Exercise the accessibility panel on an owned Wayland window with fake effects."""
import argparse
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    for key, name in (('HOME', 'home'), ('XDG_CONFIG_HOME', 'config'),
                      ('XDG_DATA_HOME', 'data'), ('XDG_STATE_HOME', 'state'),
                      ('XDG_CACHE_HOME', 'cache'), ('TMPDIR', 'tmp')):
        folder = root / name
        folder.mkdir(mode=0o700)
        os.environ[key] = str(folder)
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMainWindow
    from folego.core.accessibility import LABELS
    from folego.orchestration.models import ActionPlan, ResourceIdentity
    from folego.ui.accessibility_tab import AccessibilityTab
    from folego.ui.theme import apply_theme, paint_surface

    class PanelWindow(QMainWindow):
        def paintEvent(self, event):
            paint_surface(self)
            super().paintEvent(event)

    class Jobs:
        def __init__(self):
            self.calls = []

        def run(self, action, target, *, confirm=False, done):
            self.calls.append(action)
            if action == 'accessibility-activation-plan':
                plan = ActionPlan('accessibility.activate', ResourceIdentity.entry('microphone'),
                                  {'capabilities': ['microphone']})
                done({'plan': plan.to_dict()})
            elif action == 'accessibility-activate':
                plan = json.loads(target)
                report['desktop_profiles']['microphone']['state'] = 'healthy'
                report['cards'][-1].update(state='observed', detail='Cadeia de captura do cenário confirmada')
                done({'operation_id': plan['operation_id'], 'outcome': 'sucesso',
                      'reason': 'Cenário descartável confirmado', 'effects': {'capabilities': [
                          {'key': 'microphone', 'ready': True, 'outcome': 'sucesso',
                           'reason': 'Perfil e cadeia física confirmados no backend de teste'}]}})
            elif action == 'accessibility-profile-rearm':
                report['profile_guard']['circuit'].clear()
                done({'outcome': 'sucesso', 'reason': 'Disjuntor descartável rearmado'})

        def shutdown(self):
            pass

    app = QApplication([])
    app.setApplicationName('folego-qa-accessibility')
    assert QGuiApplication.platformName() == 'wayland'
    apply_theme(app, 'snes-us')
    jobs = Jobs()
    window = AccessibilityTab(jobs=jobs, inspect_fn=lambda: report, confirm_fn=lambda *args: True)
    host = PanelWindow()
    host.setCentralWidget(window)
    report = {'schema': 1, 'mono': time.monotonic(), 'backend': 'kwin',
              'policy': {'enabled': True, 'audio_reprobe_enabled': True},
              'cards': [{'key': key, 'state': 'degraded', 'detail': 'Cenário descartável'} for key in LABELS],
              'desktop_profiles': {'microphone': {'state': 'fault'}},
              'profile_guard': {'circuit': {'microphone': 'Revisão do cenário descartável'}},
              'pending_operations': ['input-fixture', 'gamepad-fixture'],
              'pending_capabilities': {'input-fixture': ['keyboard', 'pointer', 'touchpad', 'touch'],
                                       'gamepad-fixture': ['gamepad']},
              'plans': [], 'blockers': ['Operação anterior de entrada incerta']}
    report['cards'][-1]['detail'] = 'Enumeração de áudio incompleta com caminho de recuperação identificado'
    window.show_report(report)
    host.resize(800, 600)
    host.show()
    deadline = time.monotonic() + 5
    while not host.windowHandle().isExposed():
        assert time.monotonic() < deadline
        app.processEvents()
        time.sleep(.02)
    app.processEvents()
    assert not window.cards['touch'].isEnabled()
    assert window.cards['microphone'].isEnabled()
    assert window.cards['audio'].isEnabled()
    assert window.pending_choice.isVisibleTo(window)
    assert window.enable_all_button.isEnabled()
    assert window.audio_reprobe_choice.isChecked()
    assert window.scroll.horizontalScrollBar().maximum() == 0
    window.scroll.ensureWidgetVisible(window.cards['microphone'])
    app.processEvents()
    QTest.mouseClick(window.cards['microphone'], Qt.MouseButton.LeftButton)
    app.processEvents()
    assert jobs.calls == ['accessibility-activation-plan', 'accessibility-activate']
    assert window._pending == 'input-fixture'
    assert window.cards['microphone'].property('recovery') == 'ready'
    assert not window.cards['touch'].isEnabled()
    QTest.mouseClick(window.profile_rearm_buttons['microphone'], Qt.MouseButton.LeftButton)
    app.processEvents()
    assert jobs.calls[-1] == 'accessibility-profile-rearm'
    assert window._pending == 'input-fixture'
    assert host.grab().save(str(root / 'accessibility-client.png'))
    (root / 'receipt.json').write_text(json.dumps({
        'platform': QGuiApplication.platformName(), 'window': [host.width(), host.height()],
        'horizontal_scroll': 0, 'scoped_pending_preserved': True,
        'independent_microphone_button_exercised': True, 'audio_reprobe_choice_visible': True,
        'jobs': jobs.calls, 'host_effects': 0, 'input': 'synthetic Qt events',
        'capture': 'client window'}, indent=2) + '\n')
    window.stop()
    host.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
