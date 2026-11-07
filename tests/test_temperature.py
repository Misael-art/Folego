from folego.core.collector import MetricsCollector
from folego.core.sysfs import read_fan_speed, read_temperature


def sensor(root, name, values):
    folder = root / 'class/hwmon' / ('hwmon' + str(len(list(root.glob('class/hwmon/*')))))
    folder.mkdir(parents=True)
    (folder / 'name').write_text(name)
    for index, value in enumerate(values, 1): (folder / f'temp{index}_input').write_text(str(value))


def test_cpu_temperature_uses_hottest_valid_cpu_input_not_disk_or_gpu(tmp_path):
    sensor(tmp_path, 'nvme', [99000])
    sensor(tmp_path, 'amdgpu', [95000])
    sensor(tmp_path, 'acpitz', [88000])
    sensor(tmp_path, 'k10temp', [50000, 62000, 'NaN', 999999])
    assert read_temperature(tmp_path) == (62, 'k10temp')


def test_acpi_system_sensor_is_identified_when_cpu_sensor_is_unavailable(tmp_path):
    sensor(tmp_path, 'acpitz', [54000])
    assert read_temperature(tmp_path) == (54, 'acpitz')


def test_temperature_missing_invalid_and_thermal_zone_fallback(tmp_path):
    assert read_temperature(tmp_path) == (None, '')
    sensor(tmp_path, 'coretemp', ['invalid', 1000000])
    assert read_temperature(tmp_path) == (None, '')
    zone = tmp_path / 'class/thermal/thermal_zone0';zone.mkdir(parents=True)
    (zone/'type').write_text('x86_pkg_temp');(zone/'temp').write_text('43500')
    assert read_temperature(tmp_path) == (43.5, 'x86_pkg_temp')


def test_fan_speed_prefers_cpu_label_and_ignores_gpu(tmp_path):
    for number, name, speed, label in (
        (0, 'amdgpu', '3100', 'GPU'),
        (1, 'nct6775', '1800', 'SYS Fan'),
        (2, 'thinkpad', '2200', 'CPU Fan'),
    ):
        board = tmp_path / f'class/hwmon/hwmon{number}'
        board.mkdir(parents=True)
        (board / 'name').write_text(name)
        (board / 'fan1_input').write_text(speed)
        (board / 'fan1_label').write_text(label)
    assert read_fan_speed(tmp_path) == (2200, 'thinkpad · CPU Fan')


def test_fan_speed_missing_bad_and_stopped(tmp_path):
    assert read_fan_speed(tmp_path) == (None, '')
    board = tmp_path / 'class/hwmon/hwmon0'
    board.mkdir(parents=True)
    (board / 'name').write_text('thinkpad')
    fan = board / 'fan1_input'
    for value in ('invalid', '-1', '100001'):
        fan.write_text(value)
        assert read_fan_speed(tmp_path) == (None, '')
    fan.write_text('0')
    assert read_fan_speed(tmp_path) == (0, 'thinkpad · fan1')


def test_collector_carries_temperature_and_fan_from_sysfs(fake_proc, tmp_path):
    from fixtures_proc import build_proc

    build_proc(fake_proc, pids=[])
    sensor(tmp_path, 'k10temp', [56000])
    board = tmp_path / 'class/hwmon/hwmon1'
    board.mkdir()
    (board / 'name').write_text('thinkpad')
    (board / 'fan1_input').write_text('2340')
    snapshot = MetricsCollector(proc_root=fake_proc, sys_root=tmp_path).collect()
    assert (snapshot.temperature_c, snapshot.temperature_sensor) == (56, 'k10temp')
    assert (snapshot.fan_rpm, snapshot.fan_sensor) == (2340, 'thinkpad · fan1')
