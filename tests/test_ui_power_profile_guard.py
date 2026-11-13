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
        window._observe_power_profile(battery(8_300_000, 'Charging'), True)
        window._observe_power_profile(battery(8_300_000, 'Charging'), True)
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


def test_power_failure_is_visible_in_central_disk_options_and_bounded_notice(qapp):
    from folego.ui.main_window import MainWindow
    window = MainWindow(startup_defaults=False)
    try:
        notices = []
        window.tray.show_power_warning = notices.append
        window._power_result({'enabled': True, 'unavailable': True,
                              'message': 'Serviço de perfis indisponível'})
        assert 'proteção de energia indisponível' in notices[0]['title']
        assert window.options._power_guard_state['enabled'] is True
        assert 'indisponível' in window.dashboard.power_status.text()
        assert 'indisponível' in window.disk.host_health.rows['power'].text()
        assert 'Serviço de perfis' in window.dashboard.diagnostic_text()
        window._power_result({'enabled': True, 'unavailable': True, 'message': 'Ainda indisponível'})
        window._power_error('Sem resposta')
        assert len(notices) == 1
        assert window.options._power_guard_state['enabled'] is True
        window._power_result({'enabled': True, 'profile': 'balanced', 'message': 'Ativo.'})
        assert 'indisponível' not in window.dashboard.power_status.text()
        assert window._power_timer.isActive()
    finally:
        window.close()
    assert not window._power_timer.isActive()


def test_battery_charging_does_not_restore_without_external_power_proof(qapp):
    from folego.core.snapshot import BatteryInfo
    from folego.ui.main_window import MainWindow
    window = MainWindow(startup_defaults=False)
    try:
        calls = []
        window._power_controller.request = lambda action, value=None: calls.append((action, value))
        battery = BatteryInfo(80, 'Charging', voltage_uv=8_300_000)
        window._observe_power_profile(battery)
        assert not calls
        window._observe_power_profile(battery, True)
        assert calls == [('observe', 'external')]
    finally:
        window.close()


def test_resource_entrypoint_updates_power_and_invalidates_stale_values(qapp):
    import time
    from dataclasses import replace
    from test_battery import power_snapshot
    from folego.ui.main_window import MainWindow
    window = MainWindow(startup_defaults=False)
    try:
        notices = []
        window.tray.show_power_warning = notices.append
        window._power_controller.request = lambda *args: True
        now = time.monotonic()
        window.apply_snapshot(power_snapshot(now))
        window.apply_snapshot(power_snapshot(now + 5, online=False, status='Discharging'))
        assert len(notices) == 1 and 'desconectado' in notices[0]['title']
        assert 'desconectada' in window.dashboard.power_status.text()
        assert '7,70 V' in window.disk.host_health.rows['power'].text()
        window._refresh_freshness(now_mono=now + 21)
        assert 'desconhecida' in window.dashboard.power_status.text()
        assert '7,70 V' not in window.dashboard.power_status.text()
        window.apply_snapshot(replace(power_snapshot(time.monotonic()), sources=()))
        assert 'externa desconhecida' in window.dashboard.power_status.text()
    finally:
        window.close()


def test_background_status_keeps_explicit_user_choice_queued(qapp):
    from folego.ui.main_window import MainWindow
    window = MainWindow(startup_defaults=False)
    try:
        window._power_controller.future = object()
        window._power_request('disable')
        window._power_request('status')
        assert window._power_pending == 'disable'
        notices = []
        window.tray.show_power_warning = notices.append
        window._power_result({'enabled': False, 'unavailable': True,
                              'message': 'Serviço indisponível'})
        assert not notices and 'desligada' in window.dashboard.power_status.text()
    finally:
        window._power_controller.future = None
        window.close()
