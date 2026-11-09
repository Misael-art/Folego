def test_window_forwards_sag_and_charger_edges_and_reports_changes(qapp):
    from folego.core.snapshot import BatteryInfo
    from folego.ui.main_window import MainWindow
    window = MainWindow(collector_factory=None, startup_defaults=False)
    try:
        calls, notices = [], []
        window._power_controller.request = lambda action, value=None: calls.append((action, value)) or True
        window.tray.show_power_profile = notices.append
        def battery(volts, status='Discharging'):
            return BatteryInfo(80, status, 3600, voltage_uv=volts, voltage_min_design_uv=7_700_000)
        window._observe_power_profile(battery(7_650_000))   # stable: nothing to ask
        window._observe_power_profile(battery(7_000_000))
        window._observe_power_profile(battery(7_000_000))   # paced, not every sample
        window._power_asked_at -= 20
        window._observe_power_profile(battery(6_500_000))
        window._observe_power_profile(battery(8_300_000, 'Charging'))
        window._observe_power_profile(battery(8_300_000, 'Charging'))
        window._observe_power_profile(None)                  # unknown reading asks for nothing new
        assert calls == [('observe', 'attention'), ('observe', 'critical'),
                         ('observe', 'external'), ('observe', None)]
        window.options.build_desktop_options()
        change = {'from': 'performance', 'to': 'balanced', 'restore': False, 'level': 'attention'}
        window._power_result({'guard': True, 'enabled': True, 'message': 'Ativo.', 'changed': change})
        assert notices == [change] and window.options.power_guard_choice.isChecked()
        assert window.options.power_guard_choice.isEnabled()
        window._power_error('powerprofilesctl ausente')
        assert not window.options.power_guard_choice.isEnabled()
        assert 'ausente' in window.options.power_guard_status.text()
        emitted = []
        window.options.power_guard_requested.connect(emitted.append)
        window._power_result({'guard': True, 'enabled': True, 'message': 'Ativo.'})
        window.options.power_guard_choice.click()
        assert emitted == ['disable']
    finally:
        window.close()
