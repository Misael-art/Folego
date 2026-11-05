"""Host warnings stay readable in the existing Disk flow and never repair."""
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

from folego.ui.main_window import MainWindow
from folego.ui.theme import apply_theme


def _report():
    return {"observed_at": "2026-11-05T05:18:37-03:00",
            "btrfs_quality": "ok", "baseline_quality": "ok", "btrfs": [
                {"quality": "ok", "counters": {"corruption_errs": 6741},
                 "delta": {"corruption_errs": 0}}],
            "ntfs": {"quality": "ok", "count_10m": 17,
                     "index_inodes_10m": 3,
                     "mount": {"mount": "/mnt/sdcard"}},
            "services": {"quality": "ok", "items": [
                {"unit": "codex-quota-panel.service", "restarts": 403}]},
            "boots": {"quality": "ok", "items": [{}, {}, {}, {}],
                      "reason": "sem registro de desligamento; causa desconhecida"},
            "timeline": {"quality": "ok", "last_at": "2026-11-05T05:18:30-03:00"}}


def test_host_guard_uses_one_grouped_area_and_guides_without_effect(qapp, monkeypatch):
    apply_theme(qapp)
    win = MainWindow()
    win.resize(800, 600)
    win.tabs.setCurrentWidget(win.disk)
    win._show_host_report(_report())
    win.disk.show_thermal({"state": "recent_high", "sensor": "acpitz",
                           "current_c": 81, "peak_c": 97, "passive_c": 100,
                           "fan_rpm": None, "top_process": {"name": "retro-dev-studi",
                                                             "cpu_percent_of_core": 98},
                           "pressure_cpu_avg60": 5.8, "pressure_io_avg60": 1.3})
    win.show()
    qapp.processEvents()
    panel = win.disk.host_health
    assert "ACPI: 81" in panel.thermal_value.text()
    assert "RPM indisponível" in panel.thermal_detail.text()
    assert "possível volume /mnt/sdcard" in panel.rows["ntfs"].text()
    assert "3 índices identificados" in panel.rows["ntfs"].text()
    assert "+0 desde a leitura anterior" in panel.rows["btrfs"].text()
    assert "causa desconhecida" in panel.rows["reboot"].text()
    assert "última amostra local: 05/11 05:18:30" in panel.rows["reboot"].text()
    assert "itens para revisar" in win.dashboard.host_status.text()
    assert "Saúde do host" in win.dashboard.diagnostic_text()
    panel.copy_button.click()
    assert '"host"' in qapp.clipboard().text()
    assert '"thermal"' in qapp.clipboard().text()
    assert "PSI em 60 s" in panel.rows["pressure"].text()
    assert win.disk.scroll.horizontalScrollBar().maximum() == 0
    seen = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: seen.append(args[1:]))
    panel._guide("ntfs")
    assert seen and "Pelo Linux" in seen[0][1]
    assert "Sem destino suficiente" in seen[0][1]
    destination = os.environ.get("FOLEGO_HOST_GUARD_CAPTURE")
    if destination:
        assert win.grab().save(str(Path(destination)))
    win.quit()


def test_central_opens_host_details_in_existing_disk_tab(qapp):
    win = MainWindow()
    win.dashboard.host_button.click()
    assert win.tabs.currentWidget() is win.disk
    win.quit()


def test_host_guard_unknown_replaces_old_warning(qapp):
    win = MainWindow()
    win.disk.show_host_report(_report())
    win.disk.show_host_error("journal indisponível")
    assert "desconhecida" in win.disk.host_health.rows["ntfs"].text()
    assert "journal indisponível" in win.disk.host_health.updated.text()
    win.quit()


def test_btrfs_absolute_count_survives_missing_baseline(qapp):
    win = MainWindow()
    report = _report()
    report["baseline_quality"] = "unknown"
    report["baseline_reason"] = "baseline inválido"
    report["btrfs"][0]["delta"] = None
    win.disk.show_host_report(report)
    text = win.disk.host_health.rows["btrfs"].text()
    assert "6.741 erros acumulados" in text
    assert "tendência ou cobertura desconhecida" in text
    win.quit()


def test_btrfs_recent_increase_remains_visible_after_stable_poll(qapp):
    win = MainWindow()
    report = _report()
    report["btrfs"][0]["recent_delta"] = {"corruption_errs": 1}
    win._show_host_report(report)
    assert "+0 desde a leitura anterior" in win.disk.host_health.rows["btrfs"].text()
    assert "+1 erro de corrupção nas últimas 24 h" in win.disk.host_health.rows["btrfs"].text()
    assert "itens para revisar" in win.dashboard.host_status.text()
    win.quit()
