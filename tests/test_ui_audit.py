"""The saved profile can be changed from Options without closing the GUI."""
import time

from folego import audit_profile
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
