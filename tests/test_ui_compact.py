"""F5 compact control: navigation only, drag never acts, position recoverable."""
import pytest
import time

from folego.core.snapshot import BatteryInfo, MemInfo, Pressure, Snapshot, SourceQuality
from folego.ui.compact import CompactWindow, MINI_HEIGHT, MINI_WIDTH, clamp_position, dock_geometry
from folego.ui.desktop_caps import detect

pytest.importorskip("PySide6")


def snap(available_kb=5_000_000, total_kb=14_374_304):
    return Snapshot(ts=0.0, mem=MemInfo(total_kb, available_kb),
                    swap_used_kb=0, swap_total_kb=0,
                    pressure_memory=Pressure(0, 0, 0, 0),
                    pressure_io=None, pressure_cpu=None, load=None,
                    apps=(), self_rss_kb=90_000)


class Store:
    def __init__(self, value=""):
        self.data = {"compact/position": value}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value

    def sync(self):
        pass


class Host:
    def __init__(self):
        self.raised = 0
        self.quits = 0
        self.paused = False

    def raise_to_user(self):
        self.raised += 1

    def quit(self):
        self.quits += 1

    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused


def wayland():
    return detect(session_type="wayland", platform="wayland", tray=True)


def x11():
    return detect(session_type="x11", platform="xcb", tray=True)


def make(qapp, *, caps=None, store=None):
    host = Host()
    view = CompactWindow(host, caps=caps or x11(), store=store or Store("100,100"))
    return view, host


def test_dock_geometry_respects_available_screen_and_panels():
    from PySide6.QtCore import QRect
    area = QRect(24, 38, 1500, 812)
    assert dock_geometry('right', area) == QRect(1399, 38, 125, 812)
    assert dock_geometry('left', area) == QRect(24, 38, 125, 812)
    assert dock_geometry('top', area) == QRect(24, 38, 1500, 120)
    assert dock_geometry('top', QRect(0, 0, 948, 593)) == QRect(0, 0, 948, 120)
    assert dock_geometry('top', QRect(0, 0, 700, 500)) == QRect(0, 0, 700, 190)
    with pytest.raises(ValueError):
        dock_geometry('bottom', area)


def test_battery_adapts_to_all_widget_positions(qapp):
    from dataclasses import replace
    view, _ = make(qapp)
    sample = replace(snap(), mono=time.monotonic(),
                     battery=BatteryInfo(25, 'Discharging', 3600),
                     sources=(SourceQuality('battery', 'ok'),))
    view.show_compact()
    for mode in ('compact', 'left', 'right', 'top'):
        if mode != 'compact':
            view.set_dock_mode(mode)
            qapp.processEvents()
        view.show_snapshot(sample)
        if mode == 'top':
            assert not view.battery_label.isVisible()
            assert '25%' in view.detail_label.text()
            assert '1h00' in view.detail_label.text()
        else:
            assert view.battery_label.isVisible()
            assert '25%' in view.battery_label.text()
            assert '1h00' in view.battery_label.text()
        assert view._battery_band == 'orange'
    view.show_snapshot(replace(sample, battery=None,
                               sources=(SourceQuality('battery', 'error'),)))
    assert not view.battery_label.isVisible()
    view.show_snapshot(replace(sample, mono=time.monotonic() - 30))
    assert not view.battery_label.isVisible()
    view.force_close()


def test_dock_reflows_existing_controls_and_returns_to_compact(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QBoxLayout
    from PySide6.QtTest import QTest
    view, _ = make(qapp)
    view.show_compact()
    original = view.geometry()
    for mode in ('right', 'left', 'top'):
        view.set_dock_mode(mode)
        QTest.qWait(450)
        assert view.action_drawer.maximumHeight() == 0
        view._animate_actions(True)
        QTest.qWait(180)
        assert view._dock_mode == mode
        assert view.geometry() == dock_geometry(mode, view._screen_area())
        assert view.ai_strip.layout().direction() == (QBoxLayout.Direction.TopToBottom
            if mode in ('right', 'left') else QBoxLayout.Direction.LeftToRight)
        assert view.open_button.parent() is not None
        assert view.pause_button.parent() is not None
        assert view._handles['back'].isVisible()
        assert view._handles['back'].geometry().bottom() < view.action_drawer.geometry().top()
        actions = [view.shortcut_tabs.buttons[key] for key in
                   ('select_all', 'delete_all', 'prompts', 'copy', 'paste', 'print')]
        positions = [button.mapTo(view, QPoint(0, 0)) for button in actions]
        if mode in ('right', 'left'):
            assert view.width() <= 128
            assert view._handles['back'].x() == (0 if mode == 'left' else view.width() - 16)
            assert view.detail_label.alignment() == (Qt.AlignmentFlag.AlignLeft if mode == 'left'
                                                     else Qt.AlignmentFlag.AlignRight)
            assert all(positions[i].y() < positions[i + 1].y() for i in range(5))
            assert view.pause_button.parent() is view.notice_widget
            assert view.free_label.parent() is view.readings_widget
            assert view.action_drawer.maximumHeight() >= view.shortcut_tabs.sizeHint().height()
        else:
            assert all(abs(point.y() - positions[0].y()) <= 1 for point in positions)
        assert not view.mask().contains(QPoint(0, 0))
        assert view.mask().contains(QPoint(view.width() // 2, 0))
        view.set_dock_mode('compact')
        QTest.qWait(450)
        assert view.width() == original.width()
        assert view._dock_mode == 'compact'
    view.force_close()


def test_wayland_dock_waits_for_confirmed_placement(qapp, monkeypatch):
    view, _ = make(qapp, caps=wayland())
    requested = []
    controller = view.shortcut_tabs.controller
    monkeypatch.setattr(controller, 'request', lambda action, value=None: requested.append((action, value)) or True)
    view.show_compact()
    view.set_dock_mode('right')
    assert view._dock_pending == 'right'
    assert requested[-1][0] == 'widget-geometry'
    view.set_dock_mode('left')
    assert len(requested) == 1
    view._capture_result({'operation': 'widget-geometry', 'geometry': (20, 120, 280, 185)})
    assert requested[-1][0] == 'widget-place'
    assert view._compact_geometry.topLeft().x() == 20
    view._capture_result({'operation': 'widget-place', 'geometry': requested[-1][1]})
    assert view._dock_pending is None
    view.force_close()


def test_wayland_floating_widget_clamps_after_kwin_initial_position(qapp, monkeypatch):
    from PySide6.QtCore import QRect
    from PySide6.QtTest import QTest
    view, _ = make(qapp, caps=wayland())
    view._screen_area = lambda: QRect(0, 0, 948, 593)
    view._screens = lambda: ((0, 0, 948, 593),)
    requested = []
    monkeypatch.setattr(view.shortcut_tabs.controller, 'request',
                        lambda action, value=None: requested.append((action, value)) or True)
    view.show_compact()
    QTest.qWait(100)
    assert requested == [('widget-geometry', None)]
    view._capture_result({'operation': 'widget-geometry',
                          'geometry': (604, 368, 280, 256)})
    assert requested[-1] == ('widget-place', (604, 337, 280, 256))
    view._capture_result({'operation': 'widget-place', 'geometry': requested[-1][1]})
    assert view._show_clamp_phase is None
    view.force_close()


def test_dock_choice_during_floating_geometry_check_is_kept(qapp, monkeypatch):
    from PySide6.QtCore import QRect
    view, _ = make(qapp, caps=wayland())
    view._screen_area = lambda: QRect(0, 0, 948, 593)
    view._screens = lambda: ((0, 0, 948, 593),)
    requested = []
    monkeypatch.setattr(view.shortcut_tabs.controller, 'request',
                        lambda action, value=None: requested.append((action, value)) or True)
    view.show_compact()
    view._reconcile_compact_after_show()
    view.set_dock_mode('left')
    assert view._requested_mode == 'left'
    view._capture_result({'operation': 'widget-geometry',
                          'geometry': (604, 368, 280, 256)})
    qapp.processEvents()
    assert requested[-1][0] == 'widget-geometry'  # original floating position for return
    view._capture_result({'operation': 'widget-geometry',
                          'geometry': (604, 337, 280, 256)})
    assert requested[-1] == ('widget-place', (0, 0, 112, 593))
    view._capture_result({'operation': 'widget-place', 'geometry': requested[-1][1]})
    assert view._dock_mode == 'left' and view._dock_pending is None
    view.force_close()


def test_dock_remap_rechecks_kwin_and_corrects_late_rule(qapp, monkeypatch):
    from PySide6.QtCore import QRect
    view, _ = make(qapp, caps=wayland())
    view._screen_area = lambda: QRect(0, 0, 948, 593)
    requested = []
    monkeypatch.setattr(view.shortcut_tabs.controller, 'request',
                        lambda action, value=None: requested.append((action, value)) or True)
    view.show()
    qapp.processEvents()
    assert view.windowHandle().isExposed()
    view._dock_mode = 'top'
    view._dock_verify_attempts = 3
    view._verify_dock_after_show()
    assert requested[-1] == ('widget-geometry', None)
    view._capture_result({'operation': 'widget-geometry',
                          'geometry': (604, 368, 948, 120)})
    assert requested[-1] == ('widget-place', (0, 0, 948, 120))
    view._capture_result({'operation': 'widget-place', 'geometry': requested[-1][1]})
    assert view._dock_verify_attempts == 2
    view.force_close()


def test_dock_recheck_waits_for_busy_shortcut_controller(qapp, monkeypatch):
    from PySide6.QtCore import QRect
    from PySide6.QtTest import QTest
    view, _ = make(qapp, caps=wayland())
    view._screen_area = lambda: QRect(0, 0, 948, 593)
    requested = []
    controller = view.shortcut_tabs.controller
    monkeypatch.setattr(controller, 'request',
                        lambda action, value=None: requested.append((action, value)) or True)
    view.show()
    view._dock_mode = 'top'
    view._dock_verify_attempts = 1
    controller.future = object()
    view._verify_dock_after_show()
    assert view._dock_verify_waits == 1 and not requested
    controller.future = None
    QTest.qWait(120)
    assert requested == [('widget-geometry', None)]
    view.force_close()


def test_initial_place_failure_after_remap_rechecks_owned_geometry(qapp, monkeypatch):
    from PySide6.QtCore import QRect
    from PySide6.QtTest import QTest
    view, _ = make(qapp, caps=wayland())
    area = QRect(0, 0, 948, 593)
    view._screen_area = lambda: area
    view._dock_target = dock_geometry('left', area)
    controller = view.shortcut_tabs.controller
    requested = []
    monkeypatch.setattr(controller, 'request',
                        lambda action, value=None: requested.append((action, value)) or True)
    view.show()
    qapp.processEvents()
    assert view.windowHandle().isExposed()
    view._dock_mode = view._dock_pending = 'left'
    view._dock_verify_attempts = 3
    controller.action = 'widget-place'
    view._capture_failed('Janela ainda não mapeada')
    assert view._dock_pending is None and not requested
    QTest.qWait(220)
    assert requested == [('widget-geometry', None)]
    view.force_close()


def test_docked_widget_reapplies_edge_after_remapping(qapp):
    from PySide6.QtCore import QRect
    from PySide6.QtTest import QTest
    view, _ = make(qapp, caps=x11())
    area = QRect(0, 0, 948, 593)
    view._screen_area = lambda: area
    view.show_compact()
    view.set_dock_mode('top')
    QTest.qWait(300)
    view.hide()
    view.move(604, 368)  # KWin's floating position rule on remap
    view.show_compact()
    qapp.processEvents()
    assert view.geometry() == dock_geometry('top', area)
    view.force_close()


def test_widget_position_menu_switches_docks_and_floating(qapp):
    from PySide6.QtCore import QRect
    from PySide6.QtTest import QTest
    view, _ = make(qapp, caps=x11())
    view._screen_area = lambda: QRect(0, 0, 948, 593)
    view.show_compact()
    view.set_dock_mode('top')
    QTest.qWait(300)
    assert [action.text() for action in view.layout_menu.actions()] == [
        'Mini horizontal', 'Widget compacto', 'Lateral esquerda',
        'Lateral direita', 'Barra superior']
    view.layout_actions['left'].trigger()
    QTest.qWait(300)
    assert view._dock_mode == 'left'
    assert view.geometry() == dock_geometry('left', view._screen_area())
    view.layout_actions['compact'].trigger()
    QTest.qWait(300)
    assert view._dock_mode == 'compact' and view.width() == 280
    view.force_close()


def test_mini_bar_is_one_line_and_every_form_has_a_direct_route(qapp):
    from dataclasses import replace
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    view, host = make(qapp)
    sample = replace(snap(), mono=time.monotonic(), cpu_busy_frac=.18,
                     temperature_c=81, temperature_sensor='acpitz',
                     sources=(SourceQuality('meminfo', 'ok'), SourceQuality('cpu', 'ok'),
                              SourceQuality('temperature', 'ok')))
    view.show_compact()
    view.show_snapshot(sample)
    view.layout_actions['mini'].trigger()
    QTest.qWait(320)
    assert view._dock_mode == 'mini'
    assert (view.width(), view.height()) == (MINI_WIDTH, MINI_HEIGHT)
    assert view.mini_bar.isVisible() and not view.body_widget.isVisible()
    assert view.mini_cpu.text() == 'CPU 18%'
    assert view.mini_temperature.text() == 'ACPI 81 °C'
    assert view.mini_memory.text().startswith('RAM ')
    assert view.layout_actions['mini'].isChecked()
    hot = replace(sample, temperature_c=105, thermal_passive_c=100,
                  thermal_critical_c=105)
    view.show_snapshot(hot)
    assert 'Crítico' in view.mini_status.text()
    assert 'Limite térmico crítico' in view.mini_status.toolTip()
    low = replace(sample, battery=BatteryInfo(9, 'Discharging'),
                  sources=sample.sources + (SourceQuality('battery', 'ok'),))
    view.show_snapshot(low)
    assert 'Bateria 9%' in view.mini_status.text()
    view._shortcut_result('Posicionamento não confirmado')
    assert 'Aviso' in view.mini_status.text()
    assert 'Posicionamento não confirmado' in view.mini_status.toolTip()
    view.feedback_timer.stop()
    view._clear_feedback()
    assert 'Bateria 9%' in view.mini_status.text()
    assert all(not handle.isVisible() for handle in view._handles.values())
    view._animate_actions(True)
    assert view.action_drawer.maximumHeight() == 0
    controls = [view.mini_drag, view.mini_status, view.mini_cpu,
                view.mini_temperature, view.mini_memory, view.mini_expand,
                view.navigation_group]
    positions = [control.mapTo(view, QPoint(0, 0)).x() for control in controls]
    assert positions == sorted(positions)
    assert positions[-1] + view.navigation_group.width() <= view.width()
    for mode in ('right', 'left', 'top', 'mini'):
        view.layout_actions[mode].trigger()
        QTest.qWait(320)
        assert view._dock_mode == mode
        assert view.layout_actions[mode].isChecked()
    view.mini_expand.click()
    QTest.qWait(320)
    assert view._dock_mode == 'compact' and view.width() == 280
    view.layout_actions['mini'].trigger()
    QTest.qWait(320)
    view.open_button.click()
    assert host.raised == 1 and not view.isVisible()
    view.force_close()


def test_mini_bar_hides_stale_values_and_wayland_requests_confirmed_move(qapp, monkeypatch):
    from dataclasses import replace
    from PySide6.QtCore import QRect
    view, _ = make(qapp, caps=wayland())
    view._screen_area = lambda: QRect(0, 0, 948, 593)
    view._screens = lambda: ((0, 0, 948, 593),)
    requested = []
    monkeypatch.setattr(view.shortcut_tabs.controller, 'request',
                        lambda operation, value=None: requested.append((operation, value)) or True)
    view.show_compact()
    view.set_dock_mode('mini')
    assert requested[-1][0] == 'widget-geometry'
    view._capture_result({'operation': 'widget-geometry', 'geometry': (100, 100, 280, 160)})
    assert requested[-1] == ('widget-place', (100, 100, MINI_WIDTH, MINI_HEIGHT))
    view._capture_result({'operation': 'widget-place', 'geometry': requested[-1][1]})
    assert view._dock_mode == 'mini' and view._dock_pending is None
    sample = replace(snap(), mono=time.monotonic() - 30, cpu_busy_frac=.99,
                     temperature_c=100, temperature_sensor='acpitz',
                     sources=(SourceQuality('meminfo', 'ok'), SourceQuality('cpu', 'ok'),
                              SourceQuality('temperature', 'ok')))
    view.show_snapshot(sample)
    assert view.mini_cpu.text() == 'CPU —'
    assert view.mini_temperature.text() == '— °C'
    assert view.mini_memory.text() == 'RAM —'
    view.set_dock_mode('right')
    assert requested[-1][0] == 'widget-geometry'
    view._capture_result({'operation': 'widget-geometry', 'geometry': (100, 100, MINI_WIDTH, MINI_HEIGHT)})
    assert requested[-1][0] == 'widget-place'
    view.force_close()


def test_mini_grip_moves_only_its_window_and_saves_position(qapp):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    store = Store('100,100')
    view, host = make(qapp, store=store)
    view.show_compact()
    view.set_dock_mode('mini')
    QTest.qWait(320)
    origin = view.pos()
    local = QPoint(8, 16)
    start = view.mini_drag.mapToGlobal(local)

    def event(kind, global_point, buttons):
        return QMouseEvent(kind, QPointF(local), QPointF(global_point),
                           Qt.MouseButton.LeftButton, buttons,
                           Qt.KeyboardModifier.NoModifier)

    view.mini_drag.mousePressEvent(event(QEvent.Type.MouseButtonPress, start,
                                        Qt.MouseButton.LeftButton))
    moved = start + QPoint(30, 20)
    view.mini_drag.mouseMoveEvent(event(QEvent.Type.MouseMove, moved,
                                       Qt.MouseButton.LeftButton))
    view.mini_drag.mouseReleaseEvent(event(QEvent.Type.MouseButtonRelease, moved,
                                          Qt.MouseButton.NoButton))
    assert view.pos() == origin + QPoint(30, 20)
    assert store.data['compact/position'] == f'{view.x()},{view.y()}'
    assert host.raised == 0 and host.quits == 0
    view.force_close()


def _four_quotas(view):
    from folego.core import ai_sessions as ai
    from PySide6.QtWidgets import QApplication
    monitor = view.ai_strip.monitor
    monitor.pause()
    deadline = time.monotonic() + 2
    while monitor.poller._inflight or monitor.delivery_poller._inflight:
        monitor.poller.drain()
        monitor.delivery_poller.drain()
        QApplication.processEvents()
        assert time.monotonic() < deadline
        time.sleep(.01)
    now = time.time()
    items = []
    for provider, remaining in (('codex', 90), ('web', 70), ('claude', 50), ('grok', 30)):
        item = ai.unknown(provider, label='Conta QA')
        item.update(account_id=provider + '-qa', default=True, observed_at=now,
                    windows=[ai.quota_window('Sessão QA', 100 - remaining, now + 3600, now)])
        items.append(item)
    deliveries = [dict(provider=item['provider'], count=1, pending=[])
                  for item in items]
    monitor.poller._collect = lambda: items
    monitor.delivery_poller._collect = lambda: deliveries
    view.ai_strip.set_items(items)
    view.ai_strip.set_deliveries(deliveries)


@pytest.mark.parametrize('width,height', ((948, 593), (1280, 760), (1920, 1080), (2560, 1080)))
@pytest.mark.parametrize('mode', ('left', 'right'))
def test_side_dock_reaches_all_quotas_above_fixed_actions(qapp, width, height, mode):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtTest import QTest
    view, _ = make(qapp)
    view._screen_area = lambda: QRect(0, 0, width, height)
    view.show_compact()
    view.show_snapshot(snap())
    _four_quotas(view)
    view.set_dock_mode(mode)
    QTest.qWait(450)
    keyboard = view.shortcut_tabs.buttons['keyboard']
    keyboard_position = keyboard.mapTo(view, QPoint(0, 0))
    view._animate_actions(True)
    QTest.qWait(180)
    scroll = view.dock_scroll.verticalScrollBar()
    assert view.geometry() == dock_geometry(mode, QRect(0, 0, width, height))
    bottom = view.dock_scroll.mapTo(view, QPoint(0, view.dock_scroll.height())).y()
    assert bottom <= view.action_drawer.y()
    assert all(column.isVisible() for column in view.ai_strip.columns.values())
    if height == 593:
        assert scroll.maximum() > 0
    scroll.setValue(scroll.maximum())
    qapp.processEvents()
    assert keyboard.mapTo(view, QPoint(0, 0)) == keyboard_position
    assert view.side_content.width() == view.dock_scroll.viewport().width()
    for group in (view.keyboard_group, view.navigation_group):
        left = group.mapTo(view, QPoint(0, 0)).x()
        assert 0 <= left and left + group.width() <= view.width()
    last = view.ai_strip.columns['grok']
    top = last.mapTo(view.dock_scroll.viewport(), QPoint(0, 0)).y()
    assert top >= 0
    assert top + last.height() <= view.dock_scroll.viewport().height()
    assert view._handles['back'].x() == (0 if mode == 'left' else view.width() - 16)
    view.force_close()


@pytest.mark.parametrize('width,height', ((948, 593), (1920, 1080), (2560, 1080)))
def test_top_dock_keeps_four_quotas_and_actions_inside_view(qapp, width, height):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtTest import QTest
    view, _ = make(qapp)
    view._screen_area = lambda: QRect(0, 0, width, height)
    view.show_compact()
    view.show_snapshot(snap())
    _four_quotas(view)
    view.set_dock_mode('top')
    QTest.qWait(450)
    assert view.action_drawer.maximumHeight() == 0
    view._animate_actions(True)
    QTest.qWait(180)
    assert view.geometry() == dock_geometry('top', QRect(0, 0, width, height))
    assert view.dock_scroll.geometry().bottom() < view.action_drawer.geometry().top()
    if width >= 900:
        assert view.dock_scroll.verticalScrollBar().maximum() == 0
    assert all(column.isVisible() for column in view.ai_strip.columns.values())
    viewport = view.dock_scroll.viewport()
    components = (view.gauge_widget, view.readings_widget, view.top_controls,
                  *view.ai_strip.columns.values())
    for component in components:
        position = component.mapTo(viewport, QPoint(0, 0))
        left = position.x()
        assert left >= 0 and left + component.width() <= viewport.width()
        assert position.y() >= 0 and position.y() + component.height() <= viewport.height()
    assert view._handles['back'].geometry().bottom() < view.action_drawer.y()
    if width >= 900:
        gauge_x = view.gauge_widget.mapTo(view, QPoint(0, 0)).x()
        quota_x = view.ai_strip.mapTo(view, QPoint(0, 0)).x()
        metrics_x = view.readings_widget.mapTo(view, QPoint(0, 0)).x()
        pause_x = view.pause_button.mapTo(view, QPoint(0, 0)).x()
        assert gauge_x < quota_x < metrics_x < pause_x
        assert view.brand.mapTo(view, QPoint(0, 0)).x() < quota_x
        assert view.pause_button.mapTo(view, QPoint(0, 0)).y() > view.keyboard_group.y()
        assert view.pause_button.mapTo(view, QPoint(0, 0)).y() - view.keyboard_group.y() < 40
        assert pause_x + view.pause_button.width() <= view.width()
    view.force_close()


# --------------------------------------------------------------------- capabilities

def test_wayland_does_not_pretend_to_support_absolute_placement():
    caps = wayland()
    assert caps.tray is True
    assert caps.absolute_position is False and caps.keep_above is False
    assert caps.compact_fallback is True
    assert "Wayland" in caps.note


def test_x11_exposes_placement_and_keep_above():
    caps = x11()
    assert caps.absolute_position and caps.keep_above
    assert caps.compact_fallback is False


def test_an_unknown_session_presumes_nothing():
    caps = detect(session_type=None, platform="unknown", tray=False)
    assert caps.absolute_position is False and caps.keep_above is False
    assert caps.autostart_hint is False


def test_hotplug_clamps_a_saved_position_onto_a_live_screen():
    screens = ((0, 0, 1920, 1080), (1920, 0, 1280, 800))
    assert clamp_position(2500, 100, 360, 190, screens) == (2500, 100)
    # the second monitor vanished: the saved point is no longer visible
    assert clamp_position(2500, 100, 360, 190, ((0, 0, 1920, 1080),)) == \
        (780, 445)
    assert clamp_position(10, 10, 360, 190, ()) == (0, 0)


def test_partial_overlap_keeps_all_controls_inside_the_screen():
    assert clamp_position(1900, 1000, 360, 190, ((0, 0, 1920, 1080),)) == (1560, 890)


def test_wayland_widget_never_takes_focus_nor_restores_absolute_coordinates(qapp):
    from PySide6.QtCore import Qt
    store = Store("5000,5000")
    view, _ = make(qapp, caps=wayland(), store=store)
    flags = view.windowFlags()
    assert flags & Qt.FramelessWindowHint and flags & Qt.WindowDoesNotAcceptFocus
    assert view.windowType() == Qt.Tool
    # keep-above is not provable on Wayland: it comes from the optional KWin rule, not from a hint
    assert not flags & Qt.WindowStaysOnTopHint
    view.show_compact()
    view._save_position()
    assert store.data["compact/position"] == "5000,5000"
    view.force_close()


def test_hotplug_repositions_an_already_open_x11_control(qapp, monkeypatch):
    view, _ = make(qapp)
    view.show_compact()
    view.move(1900, 1000)
    monkeypatch.setattr(view, "_screens", lambda: ((0, 0, 800, 600),))
    view._screen_changed()
    assert view.x() >= 0 and view.y() >= 0
    assert view.x() + view.width() <= 800
    assert view.y() + view.height() <= 600
    view.force_close()


# ------------------------------------------------------------------------- display

def test_the_health_alert_survives_a_later_completed_operation(qapp):
    view, _ = make(qapp)
    view.show_snapshot(snap(available_kb=100_000))
    alert = view.signal_label.text()
    assert "🔴" in alert

    view.set_operation("disk.quarantine · sucesso")

    assert view.signal_label.text() == alert, (
        "a completed operation must not erase a persistent health alert")
    assert "disk.quarantine · sucesso" in view.operation_label.text()


def test_the_compact_control_shows_the_real_automation_state(qapp):
    view, _ = make(qapp)
    view.set_automation(mode="assistido", preset="foco", active_grants=1)
    text = view.mode_label.text()
    assert "automação assistido" in text and "preset foco" in text
    assert "1 grant(s)" in text and "execução real desligada" in text
    assert "manual" not in text

    view.set_paused(True)
    assert "PAUSADO" in view.mode_label.text()
    assert "assistido" in view.mode_label.text()


def test_an_illegible_automation_state_is_not_drawn_as_manual(qapp):
    view, _ = make(qapp)
    view.set_automation(mode="desconhecido", preset="desconhecido",
                        error="registro ilegível")
    assert "ilegível" in view.mode_label.text()
    assert "fail-closed" in view.mode_label.text()
    assert "manual" not in view.mode_label.text()


def test_pause_is_a_distinct_state_and_says_so(qapp):
    view, host = make(qapp)
    view.pause_button.click()
    assert host.paused is True
    assert "PAUSADO" in view.mode_label.text()
    assert view.pause_button.toolTip() == "Retomar monitoramento"
    assert view.pause_button.accessibleDescription() == "monitoramento pausado"

    view.pause_button.click()
    assert host.paused is False
    assert "ativo" in view.mode_label.text()


def test_repeated_navigation_clicks_do_not_create_any_operation(qapp):
    view, host = make(qapp)
    view.open_button.click()
    view.open_button.click()
    assert host.raised == 2
    assert host.quits == 0
    assert "nenhuma" in view.operation_label.text(), (
        "navigation is not an operation and must not invent one")


def test_a_drag_moves_the_window_and_triggers_no_host_action(qapp):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    view, host = make(qapp, store=Store("100,100"))
    view.show_compact()
    qapp.processEvents()
    origin = view.pos()

    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(10, 10),
                        QPointF(110, 110), Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(40, 40),
                       QPointF(140, 140), Qt.MouseButton.NoButton,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(40, 40),
                          QPointF(140, 140), Qt.MouseButton.LeftButton,
                          Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    view.mousePressEvent(press)
    view.mouseMoveEvent(move)
    view.mouseReleaseEvent(release)

    assert view.pos() != origin
    assert (host.raised, host.quits, host.paused) == (0, 0, False)


def test_an_offscreen_saved_position_is_brought_back_before_showing(qapp):
    store = Store("5000,5000")
    view, _ = make(qapp, store=store)
    view.show_compact()
    qapp.processEvents()

    screens = view._screens()
    assert screens
    sx, sy, sw, sh = screens[0]
    assert sx <= view.x() < sx + sw
    assert sy <= view.y() < sy + sh


def test_closing_the_compact_control_only_hides_it(qapp):
    view, _ = make(qapp)
    view.show_compact()
    view.close()
    assert not view.isVisible()
    view.force_close()


def test_the_widget_button_returns_to_the_central_window_and_folds_itself(qapp):
    view, host = make(qapp)
    view.show_compact()
    view.open_button.click()
    assert host.raised == 1 and not view.isVisible()


def test_widget_header_uses_navigation_and_control_menu_instead_of_window_buttons(qapp):
    view,host=make(qapp)
    assert view.open_button.text()=='' and not view.open_button.icon().isNull()
    assert view.open_button.accessibleName()=='Abrir a central do Fôlego'
    assert not hasattr(view,'hide_button') and not hasattr(view,'quit_button')
    assert [a.text() for a in view.control_menu.actions()]==[
        'Mini horizontal', 'Widget compacto', 'Lateral esquerda',
        'Lateral direita', 'Barra superior', 'Abrir Central', '',
        'Contas e cotas de IA', 'Ocultar widget', 'Sair do Fôlego']
    view._refresh_accounts_menu()
    assert len(view.accounts_menu.actions())==4
    assert all('sem confirmação' in action.text() for action in view.accounts_menu.actions())
    from folego.core import ai_sessions as ai
    import time
    item=ai.unknown('codex')
    item['reset_credits']=dict(available=2,observed_at=time.time())
    view.ai_strip.set_items([item])
    view._refresh_accounts_menu()
    assert '2 tickets' in view.accounts_menu.actions()[0].text()
    assert not view.ai_strip.columns['codex'].isVisible()
    view.quit_action.trigger()
    assert host.quits==1


def test_the_widget_shows_the_basic_numbers_and_a_mini_gauge(qapp):
    from folego.core.snapshot import MemInfo, Snapshot
    view, _ = make(qapp)
    snapshot = Snapshot(ts=0.0, mem=MemInfo(10_000_000, 3_000_000), swap_used_kb=500, swap_total_kb=1000,
                        pressure_memory=None, pressure_io=None, pressure_cpu=None, load=None,
                        apps=(), self_rss_kb=0, errors=(), tmpfs=(), sources=())
    view.show_snapshot(snapshot)
    text = view.detail_label.text()
    assert "RAM 70%" in text and "Swap 50%" in text
    assert view.gauge.value == 30


def test_cooler_speed_stays_next_to_temperature_in_each_position(qapp):
    from dataclasses import replace

    view, _ = make(qapp)
    sample = replace(snap(), temperature_c=56, temperature_sensor='k10temp',
                     fan_rpm=2340, fan_sensor='thinkpad · CPU Fan')
    for mode in ('compact', 'left', 'right', 'top'):
        if mode != 'compact':
            view.set_dock_mode(mode)
            qapp.processEvents()
        view.show_snapshot(sample)
        text = view.detail_label.text()
        assert text.index('56 °C') < text.index('2340 RPM')
        if mode == 'compact':
            assert text.count('<tr>') == 3
            assert '<tr><td>56 °C</td><td align="right">2340 RPM</td></tr>' in text
        assert 'thinkpad · CPU Fan' in view.detail_label.toolTip()
    view.show_snapshot(replace(sample, fan_rpm=None, fan_sensor=''))
    assert '— RPM' in view.detail_label.text()
    assert 'RPM indisponível' in view.detail_label.toolTip()
    view.show_snapshot(replace(sample, temperature_sensor='acpitz'))
    assert 'ACPI 56 °C' in view.detail_label.text()
    assert 'não confirma temperatura da CPU' in view.detail_label.toolTip()
    view.force_close()
