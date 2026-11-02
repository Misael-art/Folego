from folego.core.sysfs import read_temperature


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
