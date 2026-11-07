from pathlib import Path

from folego.core.battery_alerts import BatteryAlertTracker, battery_band, remaining_text
from folego.core.snapshot import BatteryInfo
from folego.core.sysfs import read_battery, read_external_power
from folego.core.collector import MetricsCollector
from folego.core.notification_tones import pcm


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
    assert battery == BatteryInfo(49, 'Discharging', 7200)
    (path / 'time_to_empty_avg').write_text('3600')
    assert read_battery(tmp_path)[0].remaining_s == 3600
    (path / 'time_to_empty_avg').write_text('not-a-number')
    (path / 'energy_now').unlink()
    (path / 'power_now').unlink()
    (path / 'charge_now').write_text('900000')
    (path / 'current_now').write_text('450000')
    assert read_battery(tmp_path)[0].remaining_s == 7200


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
    supply(tmp_path, percent='25', time_to_empty_now='1200')
    snapshot = MetricsCollector(proc_root=fake_proc, sys_root=tmp_path).collect()
    assert snapshot.battery == BatteryInfo(25, 'Discharging', 1200)
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
