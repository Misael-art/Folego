"""The saved profile can be changed from Options without closing the GUI."""
import time

from folego import audit_profile
from folego.core.snapshot import BatteryInfo
from folego.ui.audit_tab import AuditTab
from folego.ui.main_window import MainWindow


def test_audit_options_update_running_window_and_keep_input(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    window = MainWindow()
    assert not window.options.audit_choice.isChecked()
    window.options.audit_choice.click()
    until = time.monotonic() + 5
    while window.options._audit_pending and time.monotonic() < until:
        qapp.processEvents()
        time.sleep(.01)
    assert audit_profile.status()["enabled"] is True
    assert window.options.audit_choice.isChecked()
    assert not window.tabs.isTabEnabled(window.tabs.indexOf(window.performance))
    assert window.tabs.isTabEnabled(window.tabs.indexOf(window.accessibility))
    assert window.accessibility.cards["virtual-keyboard"].isEnabled()
    assert window.accessibility.cards["gamepad"].isEnabled()
    assert not window.accessibility.cards["microphone"].isEnabled()
    window.options.audit_history.click()
    assert window.tabs.currentWidget() is window.audit
    assert audit_profile.configure(False)["ok"]
    window._refresh_profile()
    assert window.tabs.isTabEnabled(window.tabs.indexOf(window.performance))
    assert window.accessibility.cards["microphone"].isEnabled()


def test_leaving_audit_resumes_energy_from_current_sample_and_web_from_now(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert audit_profile.configure(True)["ok"]
    window = MainWindow()
    window._started = True
    calls = []
    monkeypatch.setattr(window, "_power_request", lambda action, value=None: calls.append((action, value)))
    monkeypatch.setattr(window._screen_controller, "request", lambda *args: None)
    monkeypatch.setattr(window.ai_monitor, "start", lambda **kw: calls.append(("web", kw)))
    charger = BatteryInfo(75, "Charging")
    window._observe_power_profile(charger, True)
    assert calls == []
    assert audit_profile.configure(False)["ok"]
    window._refresh_profile()
    window._observe_power_profile(charger, True)
    window._observe_power_profile(charger, True)
    assert calls == [("web", {"from_now": True}), ("observe", None), ("observe", "external")]


def test_boot_timing_is_readable_in_audit_timeline(qapp):
    tab = AuditTab()
    tab.source.setCurrentIndex(tab.source.findData("boot"))
    record = {"id": 1, "at": "2026-11-22T07:00:00+00:00", "source": "boot", "kind": "startup",
              "subject": "Total 1 min 5,500 s", "boot_id": "boot-id",
              "data": {"total_s": 65.5, "system_s": 41, "firmware_s": None}}
    tab._show_history((("boot", None), {"sources": {}, "events": [record]}))
    assert tab.table.item(0, 2).text() == "Inicialização"
    tab.table.selectRow(0)
    detail = tab.details.toPlainText()
    assert "Do firmware ao fim da inicialização  1 min 5,500 s" in detail
    assert "Do kernel ao fim da inicialização  41,000 s" in detail


def test_blocked_tabs_explain_the_auditor_and_lead_to_options(qapp, tmp_path, monkeypatch):
    # Reported on the host: tabs and "Ir para" did nothing in Auditor mode, with no feedback.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert audit_profile.configure(True)["ok"]
    window = MainWindow()
    window.show()
    qapp.processEvents()
    index = window.tabs.indexOf(window.performance)
    assert not window.tabs.isTabEnabled(index)
    assert "Modo Auditor" in window.tabs.tabToolTip(index)
    bar = window.tabs.tabBar()
    before = window.tabs.currentWidget()
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(index).center())
    assert window.tabs.currentWidget() is before
    assert window.restriction_notice.isVisible()
    assert "Desempenho" in window.restriction_notice.text() and "Modo Auditor" in window.restriction_notice.text()
    window.restriction_notice.hide()
    window.jump_to("memoria")
    assert window.tabs.currentWidget() is before and window.restriction_notice.isVisible()
    window.restriction_notice.click()
    assert window.tabs.currentWidget() is window.options and not window.restriction_notice.isVisible()
    # An enabled tab still opens normally.
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(window.tabs.indexOf(window.audit)).center())
    assert window.tabs.currentWidget() is window.audit
    assert audit_profile.configure(False)["ok"]
    window._refresh_profile()
    assert window.tabs.tabToolTip(index) == "" and not window.restriction_notice.isVisible()
    window.jump_to("memoria")
    assert window.tabs.currentWidget() is window.performance
    window.close()
