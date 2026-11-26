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


def test_internal_inputs_require_physical_driver_interfaces_and_logical_pad(tmp_path):
    drm = tmp_path / "class/drm/card0-eDP-1"
    external = drm.with_name("card0-DP-1")
    for connector in (drm, external):
        connector.mkdir(parents=True)
        (connector / "status").write_text("connected")
    setting = tmp_path / "module/hid_steam/parameters/lizard_mode"
    setting.parent.mkdir(parents=True)
    setting.write_text("Y")
    driver = tmp_path / "drivers/hid-steam"
    driver.mkdir(parents=True)
    devices = []
    for i, kind in enumerate(("keyboard", "pointer", "gamepad")):
        iface = tmp_path / f"interface-{i}"
        hid = iface / f"0003:28DE:1205.000{i}"
        node = hid / f"input/input{i}"
        node.mkdir(parents=True)
        (hid / "driver").symlink_to(driver)
        (iface / "bInterfaceNumber").write_text(f"{i:02}")
        name = "Steam Deck" if i == 2 else "Valve Software Steam Deck Controller"
        (node / "name").write_text(name)
        event = tmp_path / f"class/input/event{i}"
        event.mkdir(parents=True)
        (event / "device").symlink_to(node)
        devices.append(dict(key=kind, kinds=[kind], name=name, event=event.name,
                            deck_controller=True, stable=True))
    observe = lambda: deck_hid.desktop_inputs(tmp_path, devices)
    assert observe() == {"display": "monitor externo", "native_available": True,
                         "roles": {"keyboard": "keyboard", "pointer": "pointer"}}
    (external / "status").write_text("disconnected")
    assert observe()["display"] == "portátil"
    (external / "status").write_text("unknown")
    assert observe()["display"] == "desconhecida"
    devices.pop()
    assert not observe()["native_available"]
    (tmp_path / "interface-1/bInterfaceNumber").write_text("02")
    assert not observe()["roles"]


def test_profile_motion_requires_the_active_mappers_virtual_pointer(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(deck_hid.paths, 'sys_root', lambda: str(tmp_path))
    event = tmp_path/'class/input/event17'
    device = event/'device'
    (device/'id').mkdir(parents=True)
    (device/'capabilities').mkdir()
    (device/'name').write_text('Folego Deck Pointer')
    (device/'phys').write_text('folego/deck-map/current')
    for k, v in [('bustype', '0006'), ('vendor', '0000'), ('product', '0000')]:
        (device/'id'/k).write_text(v)
    (device/'capabilities/rel').write_text('3')
    (event/'dev').write_text('13:81')
    assert deck_hid._deck_pointer_node('current') == ('event17', os.makedev(13, 81))
    with pytest.raises(ValueError):
        deck_hid._deck_pointer_node('previous')
    with pytest.raises(ValueError):
        deck_hid._deck_pointer_node()


def test_pointer_route_change_during_probe_never_confirms_motion(monkeypatch):
    from types import SimpleNamespace
    import fcntl
    import stat
    seq = iter(['current', None])
    monkeypatch.setattr(deck_hid, '_deck_pointer_node', lambda token: ('event17', os.makedev(13, 81)))
    monkeypatch.setattr(os, 'open', lambda *a: 77)
    monkeypatch.setattr(os, 'fstat', lambda fd: SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=os.makedev(13, 81)))
    monkeypatch.setattr(os, 'close', lambda fd: None)
    monkeypatch.setattr(fcntl, 'ioctl', lambda fd, cmd, size: struct.pack('=HHHH', 6, 0, 0, 1)
                        if cmd == 0x80084502 else (3).to_bytes(8, deck_hid.sys.byteorder))
    monkeypatch.setattr(deck_hid, '_has_relative_motion', lambda fd, seconds: True)
    assert deck_hid.test_pointer_motion(lambda: next(seq))['motion'] is None
