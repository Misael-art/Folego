import os
import struct
from pathlib import Path

from folego.adapters import deck_hid


def test_motion_counts_only_relative_xy_and_silence_is_inconclusive():
    rd, wr = os.pipe()
    try:
        event = struct.Struct("@llHHi")
        for kind, code, value in [(1, 272, 1), (2, 8, 1), (2, 0, 0)]:
            os.write(wr, event.pack(0, 0, kind, code, value))
        assert not deck_hid._has_relative_motion(rd, 0.01)
        os.write(wr, event.pack(0, 0, 2, 1, -1))
        assert deck_hid._has_relative_motion(rd, 0.1)
    finally:
        os.close(wr)
        os.close(rd)


def test_raw_holder_requires_wine_and_exact_valve_device(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    service = proc / "300"
    (service / "fd").mkdir(parents=True)
    (service / "comm").write_text("winedevice.exe\n")
    (service / "exe").symlink_to("/usr/lib/wine/wine-preloader")
    sysfs = tmp_path / "sys"
    hid = sysfs / "class/hidraw/hidraw99"
    hid.mkdir(parents=True)
    device = sysfs / "devices/0003:28DE:1205.0004"
    device.mkdir(parents=True)
    interface = device.parent
    (interface / "bInterfaceNumber").write_text("02")
    (interface / "bInterfaceProtocol").write_text("00")
    (device / "driver").symlink_to("/sys/bus/hid/drivers/hid-steam")
    (hid / "device").symlink_to(device)
    # A harmless char device supplies the test rdev. No input node is opened.
    null = Path("/dev/null")
    num = null.stat().st_rdev
    fd = service / "fd/3"
    fd.symlink_to(null)
    real_readlink = os.readlink
    monkeypatch.setattr(os, "readlink", lambda path, *a, **kw:
                        "/dev/hidraw99" if Path(path) == fd else real_readlink(path, *a, **kw))
    monkeypatch.setenv("DECKWELLNESS_PROC_ROOT", str(proc))
    monkeypatch.setenv("DECKWELLNESS_SYS_ROOT", str(sysfs))
    (hid / "dev").write_text("0:0")
    assert deck_hid.wine_controller_holder() is None
    (hid / "dev").write_text(f"{os.major(num)}:{os.minor(num)}")
    assert deck_hid.wine_controller_holder() == 300
    (interface / "bInterfaceNumber").write_text("01")
    assert deck_hid.wine_controller_holder() is None
    (interface / "bInterfaceNumber").write_text("02")
    (service / "comm").write_text("other")
    assert deck_hid.wine_controller_holder() is None
