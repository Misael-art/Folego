#!/usr/bin/env python3
"""Owned Wayland window proof for Host Health; synthetic data, no host effects."""
import argparse
import json
import os
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--theme", default="snes-us", choices=("snes-us", "ps2"))
    args = parser.parse_args()
    root = args.state.resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    for name, folder in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                         ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"),
                         ("XDG_CACHE_HOME", "cache"), ("TMPDIR", "tmp")):
        path = root / folder
        path.mkdir(mode=0o700)
        os.environ[name] = str(path)
    os.environ.pop("CODEX_HOME", None)
    os.environ.pop("CLAUDE_CONFIG_DIR", None)
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
    from folego.ui.main_window import MainWindow
    from folego.ui.theme import apply_theme
    from folego.core.snapshot import BatteryInfo, Snapshot, SourceQuality

    class UnavailablePowerGuard:
        def perform(self, action, value=None):
            return {'enabled': True, 'unavailable': True,
                    'message': 'Serviço de perfis indisponível (cenário de teste)'}

        def close(self):
            pass

    app = QApplication([])
    app.setApplicationName("folego-qa-host-guard")
    apply_theme(app, args.theme)
    assert QGuiApplication.platformName() == "wayland", "KDE/Wayland indisponível"
    win = MainWindow(startup_defaults=False, power_guard=UnavailablePowerGuard())
    notices = []
    win.tray._send_notice = lambda notice: notices.append(notice) or True
    now = time.monotonic()
    for mono, online in ((now - 5, True), (now, False)):
        win.apply_snapshot(Snapshot(
            ts=time.time(), mono=mono, boot_id='qa-power', mem=None,
            swap_used_kb=0, swap_total_kb=0, pressure_memory=None,
            pressure_io=None, pressure_cpu=None, load=None, apps=(), self_rss_kb=0,
            battery=BatteryInfo(75, 'Discharging', voltage_uv=7_250_000,
                                voltage_min_design_uv=7_700_000, current_ua=2_400_000),
            external_power_online=online,
            sources=(SourceQuality('battery', 'ok'), SourceQuality('external_power', 'ok'))))
    win.resize(800, 600)
    win._show_host_report({
        "observed_at": "2026-11-05T05:18:37-03:00",
        "btrfs_quality": "ok", "baseline_quality": "ok",
        "btrfs": [{"quality": "ok", "counters": {"corruption_errs": 6741},
                   "delta": {"corruption_errs": 0}}],
        "ntfs": {"quality": "ok", "count_10m": 17,
                 "mount": {"mount": "/mnt/sdcard"}},
        "services": {"quality": "ok", "items": [
            {"unit": "codex-quota-panel.service", "restarts": 403,
             "state": "auto-restart"}]},
        "boots": {"quality": "ok", "items": [{}, {}, {}, {}],
                  "reason": "sem registro de desligamento; causa desconhecida"}})
    win.disk.show_thermal({"state": "recent_high", "sensor": "acpitz",
                           "current_c": 81, "peak_c": 97, "passive_c": 100,
                           "fan_rpm": None, "top_process": {"name": "retro-dev-studi",
                                                             "cpu_percent_of_core": 98},
                           "pressure_cpu_avg60": 5.8, "pressure_io_avg60": 1.3})
    win.show()
    until = time.monotonic() + 6
    while time.monotonic() < until:
        app.processEvents()
        if win.windowHandle() and win.windowHandle().isExposed():
            break
        time.sleep(0.02)
    assert win.windowHandle() and win.windowHandle().isExposed()
    until = time.monotonic() + 3
    while 'proteção de energia indisponível' not in win.dashboard.power_status.text().lower():
        assert time.monotonic() < until
        app.processEvents()
        time.sleep(.02)
    assert '7,25 V' in win.dashboard.power_status.text()
    assert '2,40 A' in win.disk.host_health.rows['power'].text()
    assert len(notices) == 2
    QTest.mouseClick(win.dashboard.host_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert win.tabs.currentWidget() is win.disk
    area = win.disk.scroll
    assert area.horizontalScrollBar().maximum() == 0
    assert area.verticalScrollBar().maximum() > 0
    guide_button = next(button for button in win.disk.host_health.findChildren(QPushButton)
                        if button.accessibleName() == "Ver orientação para calor e carga")
    seen = []

    def inspect_dialog():
        modal = QApplication.activeModalWidget()
        assert isinstance(modal, QMessageBox)
        seen.append((modal.windowTitle(), modal.text()))
        modal.accept()

    QTimer.singleShot(100, inspect_dialog)
    QTest.mouseClick(guide_button, Qt.MouseButton.LeftButton)
    assert seen and "ACPI" in seen[0][1]
    args.capture.parent.mkdir(parents=True, exist_ok=True)
    assert win.grab().save(str(args.capture))
    area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
    app.processEvents()
    assert area.verticalScrollBar().value() == area.verticalScrollBar().maximum()
    receipt = {"platform": QGuiApplication.platformName(), "owned_window_mapped": True,
               "window": [win.width(), win.height()], "horizontal_scroll": 0,
               "vertical_scroll_max": area.verticalScrollBar().maximum(),
               "guide": seen[0][0], "theme": args.theme,
               "power_status": win.dashboard.power_status.text(),
               "power_notices": [notice.title for notice in notices],
               "state": "synthetic", "host_effects": 0}
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    win.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
