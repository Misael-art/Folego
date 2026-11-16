from pathlib import Path
from dataclasses import replace

from folego.core.battery_alerts import BatteryAlertTracker, battery_band, remaining_text
from folego.core.snapshot import BatteryInfo
from folego.core.sysfs import read_battery, read_external_power
from folego.core.collector import MetricsCollector
from folego.core.notification_tones import pcm


def power_snapshot(mono, *, online=True, status='Charging', voltage=7_700_000):
    from folego.core.snapshot import Snapshot, SourceQuality
    return Snapshot(ts=1_700_000_000 + mono, mono=mono, boot_id='boot-1', mem=None,
                    swap_used_kb=0, swap_total_kb=0, pressure_memory=None,
                    pressure_io=None, pressure_cpu=None, load=None, apps=(), self_rss_kb=0,
                    battery=BatteryInfo(75, status, voltage_uv=voltage, current_ua=2_000_000,
                                        voltage_min_design_uv=7_700_000),
                    external_power_online=online,
                    sources=(SourceQuality('battery', 'ok'), SourceQuality('external_power', 'ok')))


def test_power_status_preserves_unknown_sources_and_reports_voltage_attention():
    from folego.core.battery_alerts import power_supply_status
    sample = power_snapshot(100, online=False, status='Discharging', voltage=7_000_000)
    report = power_supply_status(sample, now_mono=100)
    assert report['state'] == 'attention'
    assert '7,00 V' in report['message'] and '75%' in report['message']
    assert '2,00 A' in report['message'] and 'desconectada' in report['message']
    unknown = power_supply_status(replace(sample, sources=()), now_mono=100)
    assert unknown['state'] == 'unknown' and '7,00 V' not in unknown['message']
    assert 'desconhecida' in unknown['message']
    stale = power_supply_status(sample, now_mono=116)
    assert stale['state'] == 'unknown' and 'antiga' in stale['message']


def test_external_disconnect_needs_observed_edge_and_limits_repeated_notices():
    from folego.core.battery_alerts import ExternalPowerTracker
    tracker = ExternalPowerTracker()
    assert tracker.observe(power_snapshot(100, online=False), now_mono=100) is None
    assert tracker.observe(power_snapshot(105), now_mono=105) is None
    notice = tracker.observe(power_snapshot(110, online=False), now_mono=110)
    assert 'desconectado' in notice['title']
    assert tracker.observe(power_snapshot(115), now_mono=115) is None
    assert tracker.observe(power_snapshot(120, online=False), now_mono=120) is None
    # Another boot establishes its own baseline and notification budget.
    assert tracker.observe(replace(power_snapshot(125), boot_id='boot-2'), now_mono=125) is None
    assert tracker.observe(replace(power_snapshot(130, online=False), boot_id='boot-2'),
                           now_mono=130) is not None


def test_external_power_never_bridges_missing_stale_or_delayed_observations():
    from folego.core.battery_alerts import ExternalPowerTracker
    for broken in (replace(power_snapshot(105), sources=()),
                   power_snapshot(80), power_snapshot(135, online=False)):
        tracker = ExternalPowerTracker()
        assert tracker.observe(power_snapshot(100), now_mono=100) is None
        assert tracker.observe(broken, now_mono=135) is None
        assert tracker.observe(power_snapshot(140, online=False), now_mono=140) is None


def test_discharge_on_external_needs_distinct_consecutive_fresh_samples():
    from folego.core.battery_alerts import ExternalPowerTracker
    tracker = ExternalPowerTracker()
    first = power_snapshot(100, status='Discharging')
    assert tracker.observe(first, now_mono=100) is None
    assert tracker.observe(first, now_mono=101) is None
    second = power_snapshot(105, status='Discharging')
    assert 'descarregando na tomada' in tracker.observe(second, now_mono=105)['title']
    assert tracker.observe(power_snapshot(110, status='Discharging'), now_mono=110) is None


def supply(root: Path, *, percent='75', status='Discharging', **fields):
    battery = root / 'class/power_supply/BAT0'
    battery.mkdir(parents=True)
    for name, value in {'type': 'Battery', 'capacity': percent,
                        'status': status, **fields}.items():
        (battery / name).write_text(str(value))
    return battery


def test_battery_reading_and_eta_from_kernel_values(tmp_path):
    path = supply(tmp_path, percent='49', energy_now='12000000', power_now='6000000')
    battery, quality = read_battery(tmp_path)
    assert quality.status == 'ok'
    assert battery == BatteryInfo(49, 'Discharging', 7200, power_uw=6_000_000)
    (path / 'time_to_empty_avg').write_text('3600')
    assert read_battery(tmp_path)[0].remaining_s == 3600
    (path / 'time_to_empty_avg').write_text('not-a-number')
    (path / 'energy_now').unlink()
    (path / 'power_now').unlink()
    (path / 'charge_now').write_text('900000')
    (path / 'current_now').write_text('450000')
    assert read_battery(tmp_path)[0].remaining_s == 7200


def test_battery_electrical_values_keep_kernel_units_and_unknowns(tmp_path):
    path = supply(tmp_path, percent='62', status='Charging',
                  voltage_now='8176000', current_now='1752000')
    observed, quality = read_battery(tmp_path)
    assert quality.status == 'ok'
    assert observed == BatteryInfo(62, 'Charging', voltage_uv=8_176_000,
                                   current_ua=1_752_000)
    assert observed.power_uw is None  # no inferred watts or discharge direction
    (path / 'power_now').write_text('14323552')
    assert read_battery(tmp_path)[0].power_uw == 14_323_552
    (path / 'voltage_now').write_text('unreadable')
    (path / 'current_now').write_text('-7')
    (path / 'power_now').write_text('100000000000000')
    observed, quality = read_battery(tmp_path)
    assert quality.status == 'ok' and observed.percent == 62
    assert (observed.voltage_uv, observed.current_ua, observed.power_uw) == (None, None, None)


def test_battery_fail_closed_and_charging_has_no_discharge_eta(tmp_path):
    assert read_battery(tmp_path)[1].status == 'missing'
    path = supply(tmp_path, percent='bad')
    assert read_battery(tmp_path)[0] is None
    assert read_battery(tmp_path)[1].status == 'error'
    (path / 'capacity').write_text('101')
    assert read_battery(tmp_path)[0] is None
    (path / 'capacity').write_text('10')
    (path / 'status').write_text('Charging')
    (path / 'time_to_empty_now').write_text('300')
    assert read_battery(tmp_path)[0] == BatteryInfo(10, 'Charging', None)
    second = tmp_path / 'class/power_supply/BAT1'
    second.mkdir()
    (second / 'type').write_text('Battery')
    assert read_battery(tmp_path)[1].status == 'error'


def test_collector_publishes_battery_quality(fake_proc, tmp_path):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[])
    supply(tmp_path, percent='25', time_to_empty_now='1200',
           voltage_now='7600000', current_now='900000')
    snapshot = MetricsCollector(proc_root=fake_proc, sys_root=tmp_path).collect()
    assert snapshot.battery == BatteryInfo(25, 'Discharging', 1200,
                                           voltage_uv=7_600_000, current_ua=900_000)
    assert snapshot.source('battery').status == 'ok'


def test_system_battery_ignores_peripheral_and_reports_external_power(fake_proc, tmp_path):
    from fixtures_proc import build_proc
    build_proc(fake_proc, pids=[])
    supply(tmp_path, percent='90')
    peripheral = tmp_path / 'class/power_supply/hidpp_battery_1'
    peripheral.mkdir()
    (peripheral / 'type').write_text('Battery')
    (peripheral / 'scope').write_text('Device')
    adapter = tmp_path / 'class/power_supply/ACAD'
    adapter.mkdir()
    (adapter / 'type').write_text('Mains')
    (adapter / 'online').write_text('0')
    snapshot = MetricsCollector(proc_root=fake_proc, sys_root=tmp_path).collect()
    assert snapshot.battery == BatteryInfo(90, 'Discharging')
    assert snapshot.source('battery').status == 'ok'
    assert snapshot.external_power_online is False
    assert snapshot.source('external_power').status == 'ok'
    (adapter / 'online').write_text('1')
    assert read_external_power(tmp_path)[0] is True
    (adapter / 'online').write_text('unknown')
    assert read_external_power(tmp_path)[1].status == 'error'
    assert read_external_power(tmp_path)[0] is None


def test_thresholds_cross_once_and_critical_repeats_every_minute():
    tracker = BatteryAlertTracker()
    sample = lambda pct, status='Discharging': BatteryInfo(pct, status)
    assert tracker.observe(sample(90), now=0) is None
    assert tracker.observe(sample(75), now=1) == 'battery-75'
    assert tracker.observe(sample(74), now=2) is None
    assert tracker.observe(sample(49), now=3) == 'battery-50'
    assert tracker.observe(sample(24), now=4) == 'battery-25'
    assert tracker.observe(sample(9), now=5) == 'battery-10'
    assert tracker.observe(sample(8), now=64) is None
    assert tracker.observe(sample(8), now=65) == 'battery-10'
    assert tracker.observe(sample(7, 'Charging'), now=66) is None
    assert tracker.observe(sample(7), now=67) == 'battery-10'
    assert tracker.observe(None, now=68) is None
    assert tracker.observe(sample(50), now=69) is None


def test_battery_bands_and_time():
    assert [battery_band(n) for n in (100, 75, 50, 25, 10)] == [
        'green', 'green', 'yellow', 'orange', 'red']
    assert remaining_text(None) == ''
    assert remaining_text(7200) == '2h00'
    assert len({pcm(f'battery-{threshold}') for threshold in (75, 50, 25, 10)}) == 4


def test_voltage_sag_alerts_despite_gauge_percent(tmp_path):
    # Observed on 2026-11-09: gauge at 54% while a 7.7 V-design pack sagged to 6.57 V.
    from folego.core.battery_alerts import voltage_sag
    supply(tmp_path, percent='54', voltage_now='6569000', current_now='2711000',
           voltage_min_design='7700000')
    battery, quality = read_battery(tmp_path)
    assert quality.status == 'ok' and battery.voltage_min_design_uv == 7_700_000
    assert voltage_sag(battery)
    tracker = BatteryAlertTracker()
    assert tracker.observe(battery, now=0) == 'battery-10'
    assert tracker.observe(battery, now=30) is None
    assert tracker.observe(battery, now=61) == 'battery-10'


def test_voltage_sag_needs_design_reference_and_discharge():
    from folego.core.battery_alerts import voltage_sag
    assert not voltage_sag(BatteryInfo(54, 'Discharging', voltage_uv=6_569_000))
    assert not voltage_sag(BatteryInfo(54, 'Charging', voltage_uv=6_569_000,
                                       voltage_min_design_uv=7_700_000))
    assert not voltage_sag(BatteryInfo(54, 'Discharging', voltage_uv=7_400_000,
                                       voltage_min_design_uv=7_700_000))


def test_voltage_levels_follow_design_reference_only_while_discharging():
    from folego.core.battery_alerts import voltage_level

    def pack(volts, status='Discharging', design=7_700_000):
        return BatteryInfo(60, status, voltage_uv=round(volts * 1e6),
                           voltage_min_design_uv=design)
    assert [voltage_level(pack(v)) for v in (7.65, 7.39, 7.30, 7.17, 7.10, 6.94, 6.92)] == [
        'stable', 'acceptable', 'acceptable', 'acceptable', 'attention', 'attention', 'critical']
    assert voltage_level(pack(8.4, 'Charging')) is None
    assert voltage_level(pack(6.5, design=None)) is None
    assert voltage_level(None) is None


def test_voltage_notice_needs_sustained_sag_and_respects_repeat_window():
    from folego.core.battery_alerts import VoltageSagNotice
    low = BatteryInfo(54, 'Discharging', voltage_uv=6_569_000, voltage_min_design_uv=7_700_000)
    near = BatteryInfo(54, 'Discharging', voltage_uv=7_000_000, voltage_min_design_uv=7_700_000)
    fine = BatteryInfo(54, 'Discharging', voltage_uv=7_600_000, voltage_min_design_uv=7_700_000)
    notice = VoltageSagNotice()
    assert not notice.observe(low, now=0)       # one spike is not sustained
    assert notice.observe(low, now=2)
    assert not notice.observe(low, now=60)      # inside the repeat window
    assert not notice.observe(near, now=62)     # oscillation near the limit is the same event
    assert not notice.observe(low, now=64)
    assert not notice.observe(low, now=66)
    assert notice.observe(low, now=310)
    assert not notice.observe(fine, now=312)    # recovery re-arms immediately
    assert not notice.observe(low, now=314)
    assert notice.observe(low, now=316)
    assert not notice.observe(None, now=318)
