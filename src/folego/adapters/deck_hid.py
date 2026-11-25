"""Read-only observations of the Deck controller and its emulated pointer."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import sys
import time

from .. import paths


def wine_controller_holder() -> int | None:
    """Look only for a positive match in this user's Wine device services."""
    sysfs = Path(paths.sys_root()) / "class/hidraw"
    if not sysfs.is_dir():
        return None
    nodes = {}
    for entry in sysfs.iterdir():
        if not re.fullmatch(r"hidraw[0-9]+", entry.name):
            continue
        device = entry / "device"
        if not re.fullmatch(r"0003:28DE:1205\.[0-9A-Fa-f]+", device.resolve().name):
            continue
        if (device / "driver").resolve().name != "hid-steam":
            continue
        # Only the gamepad interface registers a hid-steam userspace client.
        interface = device.resolve().parent
        if ((interface / "bInterfaceNumber").read_text().strip() != "02"
                or (interface / "bInterfaceProtocol").read_text().strip() != "00"):
            continue
        major, minor = (int(value) for value in (entry / "dev").read_text().strip().split(":"))
        nodes["/dev/" + entry.name] = os.makedev(major, minor)
    if not nodes:
        return None

    deadline = time.monotonic() + 0.2
    with os.scandir(paths.proc_root()) as processes:
        for process in processes:
            if time.monotonic() >= deadline:
                raise OSError("inventário de clientes HID incompleto")
            if not process.name.isdecimal():
                continue
            directory = Path(process.path)
            try:
                if process.stat().st_uid != os.getuid() or (directory / "comm").read_text().strip() != "winedevice.exe":
                    continue
                if (directory / "exe").readlink().name not in ("wine", "wine64", "wine-preloader", "wine64-preloader"):
                    continue
                with os.scandir(directory / "fd") as descriptors:
                    for fd in descriptors:
                        if time.monotonic() >= deadline:
                            raise OSError("inventário de descritores HID incompleto")
                        try:
                            target = os.readlink(fd.path)
                            if target in nodes:
                                info = fd.stat()
                                if stat.S_ISCHR(info.st_mode) and info.st_rdev == nodes[target]:
                                    return int(process.name)
                        except FileNotFoundError:
                            continue  # Another descriptor may still own the controller.
            except (FileNotFoundError, ProcessLookupError):
                continue
    return None


def _deck_pointer_node():
    """Resolve the Valve USB relative pointer. Event numbers may change on resume."""
    matches = []
    for event in (Path(paths.sys_root()) / "class/input").glob("event[0-9]*"):
        if not re.fullmatch(r"event[0-9]+", event.name):
            continue
        device = event / "device"
        if (device / "name").read_text().strip() != "Valve Software Steam Deck Controller":
            continue
        ids = tuple((device / "id" / k).read_text().strip() for k in ("bustype", "vendor", "product"))
        if ids != ("0003", "28de", "1205"):
            continue
        rel = (device / "capabilities/rel").read_text().split()
        if rel and int(rel[-1], 16) & 3 == 3:
            major, minor = map(int, (event / "dev").read_text().strip().split(":"))
            matches.append((event.name, os.makedev(major, minor)))
    if len(matches) != 1:
        raise ValueError("saída de ponteiro Valve ausente ou ambígua")
    return matches[0]


def _has_relative_motion(fd, seconds):
    import select
    import struct

    event = struct.Struct("@llHHi")
    deadline = time.monotonic() + seconds
    while (remaining := deadline - time.monotonic()) > 0:
        if not select.select([fd], [], [], remaining)[0]:
            break
        data = os.read(fd, event.size * 32)
        if not data or len(data) % event.size:
            raise OSError("fluxo do controle interrompido")
        for _, _, kind, axis, value in event.iter_unpack(data):
            if kind == 0 and axis == 3:  # SYN_DROPPED
                raise OSError("eventos perdidos durante o teste")
            if kind == 2 and axis in (0, 1) and value:  # EV_REL, REL_X/Y
                return True
    return False


def test_pointer_motion():
    """Explicit eight-second evdev observation, no grabs, coordinates or events retained."""
    import fcntl
    import struct

    try:
        name, number = _deck_pointer_node()
        fd = os.open("/dev/input/" + name, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            # EVIOCGID and EVIOCGBIT(EV_REL, 8) on the open descriptor.
            ids = struct.unpack("=HHHH", fcntl.ioctl(fd, 0x80084502, bytes(8)))
            axes = int.from_bytes(fcntl.ioctl(fd, 0x80084522, bytes(8)), sys.byteorder)
            if (not stat.S_ISCHR(info.st_mode) or info.st_rdev != number
                    or ids[:3] != (3, 0x28de, 0x1205) or axes & 3 != 3):
                raise ValueError("identidade do ponteiro mudou")
            moved = _has_relative_motion(fd, 8)
            if _deck_pointer_node() != (name, number):
                raise ValueError("enumeração do controle mudou durante o teste")
        finally:
            os.close(fd)
    except (OSError, ValueError) as exc:
        return {"ok": False, "motion": None, "reason": f"Teste de movimento indisponível: {exc}"}
    return {"ok": True, "motion": moved, "reason": (
        "O kernel recebeu movimento do ponteiro Valve. Confira se o cursor acompanhou o gesto."
        if moved else "Nenhum movimento do ponteiro Valve em 8 s. Se você deslizou o dedo, "
                      "consulte o diagnóstico dos trackpads.")}


def desktop_inputs(sys_root, devices):
    """Identify the Deck's two firmware outputs and its logical pad at this sample."""
    root = Path(sys_root)
    roles = {}
    native_pad = False
    for device in devices:
        if not device.get("deck_controller") or not device["stable"]:
            continue
        try:
            node = (root / "class/input" / device["event"] / "device").resolve(strict=True)
            hid = node.parent.parent
            if (not re.fullmatch(r"0003:28DE:1205\.[0-9A-Fa-f]+", hid.name)
                    or (hid / "driver").resolve(strict=True).name != "hid-steam"):
                continue
            interface = (hid.parent / "bInterfaceNumber").read_text().strip()
            kind = {"00": "keyboard", "01": "pointer"}.get(interface)
            if (kind in device["kinds"] and device["name"] == "Valve Software Steam Deck Controller"
                    and (node / "name").read_text().strip() == device["name"]):
                roles[device["key"]] = kind
            elif interface == "02" and device["name"] == "Steam Deck" and "gamepad" in device["kinds"]:
                native_pad = True
        except (OSError, RuntimeError):
            continue
    mode = "desconhecida"
    try:
        statuses = {}
        for connector in (root / "class/drm").glob("card*-*"):
            name = connector.name.split("-", 1)[1]
            if not name.startswith("Writeback-"):
                statuses[connector.name] = (connector / "status").read_text().strip()
        if any("-eDP-" in k and v == "connected" for k, v in statuses.items()):
            external = [v for k, v in statuses.items() if "-eDP-" not in k]
            if "connected" in external:
                mode = "monitor externo"
            elif all(v == "disconnected" for v in external):
                mode = "portátil"
    except OSError:
        pass
    try:
        firmware = (root / "module/hid_steam/parameters/lizard_mode").read_text().strip() == "Y"
    except OSError:
        firmware = False
    roles_unique = sorted(roles.values()) == ["keyboard", "pointer"]
    return {"display": mode, "roles": roles if roles_unique else {},
            "native_available": bool(roles_unique and firmware and native_pad)}
