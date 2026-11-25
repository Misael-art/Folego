"""Event-driven PhaseZero desktop bindings for the Deck. No USB writes or driver changes."""
from contextlib import ExitStack
import fcntl
import math
import os
from pathlib import Path
import re
import select
import socket
import stat
import struct
import subprocess
import sys
import time

# Linux input-event-codes.h. Modifiers precede keys on press, follow them on release.
CTRL, SHIFT, ALT, META = 29, 42, 56, 125
TAB, ENTER, ESC, SPACE, BACKSPACE = 15, 28, 1, 57, 14
UP, RIGHT, LEFT, DOWN = 103, 106, 105, 108
PRIMARY, SECONDARY = 272, 273
MODIFIERS = (CTRL, SHIFT, ALT, META)
# Bit positions in Valve's 0x09 Deck report, also used by PhaseZero's SCC profile.
BINDINGS = {0: (PRIMARY,), 1: (SECONDARY,), 2: (CTRL, TAB), 3: (CTRL, SHIFT, TAB),
            4: (SPACE,), 5: (ESC,), 6: (BACKSPACE,), 7: (ENTER,),
            8: (UP,), 9: (RIGHT,), 10: (LEFT,), 11: (DOWN,), 12: (ALT, TAB),
            14: (META, 17), 15: (SHIFT, TAB), 16: (TAB,), 18: (PRIMARY,),
            41: (META,), 42: (META, 17)}
CHORDS = {4: (99,), 5: (CTRL, 46), 6: (), 7: (CTRL, 47)}
KEYS = sorted({k for combo in (*BINDINGS.values(), *CHORDS.values()) for k in combo})
EVENT = struct.Struct('@llHHi')
BUTTONS = struct.Struct('<Q')
PAIR = struct.Struct('<hh')
NAMES = ('Folego Deck Keyboard', 'Folego Deck Pointer')


def valid_packet(data):
    return len(data) == 64 and data[:3] == b'\x01\x00\x09'


class Layout:
    def __init__(self):
        self.held = set()
        self.keyboard = False
        self.previous = {}
        self.fraction = {}
        self.last = None
        self.bindings = {}
        self.sample = None

    def translate(self, data, now):
        # Ignore sequence counters and IMU noise while the desktop controls rest.
        sample = data[8:24], data[48:56]
        rx, ry = PAIR.unpack_from(data, 52)
        if sample == self.sample and max(abs(rx), abs(ry)) <= 4800:
            self.last = now
            return [], False
        self.sample = sample
        buttons, = BUTTONS.unpack_from(data, 8)
        steam = bool(buttons & (1 << 13))
        wanted = set()
        for bit, plain in BINDINGS.items():
            if buttons & (1 << bit):
                # Latch a chord until its action button is released.
                if bit not in self.bindings:
                    self.bindings[bit] = CHORDS.get(bit, plain) if steam else plain
                wanted.update(self.bindings[bit])
            else:
                self.bindings.pop(bit, None)
        sx, sy = PAIR.unpack_from(data, 48)
        for axis, neg, pos in ((sx, LEFT, RIGHT), (sy, DOWN, UP)):
            if abs(axis) > 15000:
                wanted.add(neg if axis < 0 else pos)
        keys = [(1, key, 0) for key in sorted(self.held - wanted, key=lambda k: (k in MODIFIERS, k))]
        keys.extend((1, key, 1) for key in sorted(wanted - self.held, key=lambda k: (k not in MODIFIERS, k)))
        self.held = wanted
        osk = bool(buttons & (1 << 50)) or self.bindings.get(6) == ()
        toggle, self.keyboard = osk and not self.keyboard, osk
        movement = {}
        for bit, offset, axes, scale in ((20, 20, (0, 1), 155), (19, 16, (6, 8), 3600)):
            if buttons & (1 << bit):
                point = PAIR.unpack_from(data, offset)
                old = self.previous.get(bit, point)
                self.previous[bit] = point
                movement[axes[0]] = (point[0] - old[0]) / scale
                movement[axes[1]] = (point[1] - old[1]) / (scale if bit == 19 else -scale)
            else:
                self.previous.pop(bit, None)
        dt = min(.04, max(0., now - self.last)) if self.last is not None else 0.
        self.last = now
        for axis, stick in enumerate((rx, ry)):
            if abs(stick) > 4800:
                delta = math.copysign((abs(stick)-4800)/27968, stick) * 900 * dt
                movement[axis] = movement.get(axis, 0) + (delta if axis == 0 else -delta)
        for axis, amount in movement.items():
            total = self.fraction.get(axis, 0.) + amount
            step = int(total)
            self.fraction[axis] = total-step
            if step:
                keys.append((2, axis, step))
        return keys, toggle


def _fd(stack, path, flags):
    fd = os.open(path, flags | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    stack.callback(os.close, fd)
    return fd


def _device_nodes(sysroot=Path('/sys')):
    result = {}
    parents = set()
    for folder, pattern in (('input', 'event*'), ('hidraw', 'hidraw*')):
        for entry in (sysroot/'class'/folder).glob(pattern):
            # The raw nodes point at the HID device, evdev at its input child.
            node = (entry/'device').resolve(strict=True)
            hid = node if folder == 'hidraw' else node.parent.parent
            if not re.fullmatch(r'0003:28DE:1205\.[A-Fa-f0-9]+', hid.name):
                continue
            if (hid/'driver').resolve().name != 'hid-steam':
                continue
            interface = (hid.parent/'bInterfaceNumber').read_text().strip()
            if (folder, interface) not in (('input', '00'), ('input', '01'), ('hidraw', '02')):
                continue
            if interface in result or (hid.parent/'bInterfaceClass').read_text().strip() != '03':
                raise ValueError('Interfaces do Deck ambíguas.')
            parents.add(hid.parent.parent)
            major, minor = map(int, (entry/'dev').read_text().strip().split(':'))
            prefix = Path('/dev/input') if folder == 'input' else Path('/dev')
            result[interface] = prefix/entry.name, os.makedev(major, minor)
    if set(result) != {'00', '01', '02'} or len(parents) != 1:
        raise ValueError('Ponteiro, teclado e HID do mesmo Deck não comprovados.')
    return result


def _virtual(stack, name, keys, rel=()):
    fd = _fd(stack, '/dev/uinput', os.O_WRONLY)
    for event in ((1, 2) if rel else (1,)):
        fcntl.ioctl(fd, 0x40045564, event)
    for key in keys:
        fcntl.ioctl(fd, 0x40045565, key)
    for axis in rel:
        fcntl.ioctl(fd, 0x40045566, axis)
    setup = struct.pack('=HHHH80sI', 6, 0, 0, 1, name.encode(), 0)
    fcntl.ioctl(fd, 0x405c5503, setup)
    fcntl.ioctl(fd, 0x5501)
    # Each kernel-created input has its own identity; never trust only its label.
    ident = fcntl.ioctl(fd, 0x8040552c, bytes(64)).split(b'\0')[0].decode()
    if not re.fullmatch(r'input\d+', ident):
        raise ValueError('Identidade da saída virtual não confirmada.')
    return fd, ident


def _ready_outputs(outputs):
    from .accessibility import NativeInput, DEVICE_ROOT, DEVICE_IFACE, PROPERTIES
    native = NativeInput()
    from shutil import which
    binary = which('qdbus6') or which('qdbus')
    if not binary:
        return False
    native.deadline = native.clock() + 3
    owner = native.call([binary, 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                         'org.freedesktop.DBus.GetNameOwner', 'org.kde.KWin']).strip()
    native.qdbus = binary
    while native.clock() < native.deadline:
        ready = []
        names = native.call([binary, owner, DEVICE_ROOT, PROPERTIES + '.Get',
                             DEVICE_IFACE+'Manager', 'devicesSysNames']).splitlines()
        for (_, ident), expected in zip(outputs, NAMES):
            nodes = list((Path('/sys/class/input')/ident).glob('event*'))
            if len(nodes) == 1 and nodes[0].name in names:
                props = native.props(owner, DEVICE_ROOT+'/'+nodes[0].name, DEVICE_IFACE)
                ready.append(props.get('enabled') == 'true' and props.get('name') == expected)
        if ready == [True, True]:
            return True
        time.sleep(.12)
    return False


def _emit(outputs, events):
    for pointer, (fd, _) in enumerate(outputs):
        group = [(t, k, v) for t, k, v in events if (t == 2 or k >= PRIMARY) == bool(pointer)]
        if group:
            payload = b''.join(EVENT.pack(0, 0, *v) for v in (*group, (0, 0, 0)))
            if os.write(fd, payload) != len(payload):
                raise OSError('Saída virtual parcial.')


def _notify():
    endpoint = os.environ['NOTIFY_SOCKET']
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.sendto(b'READY=1', ('\0'+endpoint[1:]) if endpoint.startswith('@') else endpoint)


def _session(mapping, token, stage):
    from ..actions.deck_mapping import unit_name
    from ..core.sessions import read_boot_id
    s = mapping.read()
    if (s['token'] != token or s['stage'] != stage or s['choice'] != 'phasezero'
            or s.get('boot') != read_boot_id() or not re.fullmatch(r':\d+\.\d+', s.get('kwin', ''))
            or not Path('/proc/self/cgroup').read_text().strip().endswith('/'+unit_name(token))):
        raise ValueError('Intenção do mapeador não confirmada nesta sessão.')
    return s


def _desktop_blocker(mapping, s, native):
    from ..actions.accessibility import lease_blockers
    from ..actions.deck_profile_guard import DeckProfileGuard
    native.deadline = native.clock() + 3
    native.qdbus = native.which('qdbus6') or native.which('qdbus')
    if not native.qdbus:
        raise ValueError('Canal do compositor indisponível.')
    owner = native.call([native.qdbus, 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                         'org.freedesktop.DBus.GetNameOwner', 'org.kde.KWin']).strip()
    if owner != s['kwin']:
        return 'A sessão do compositor mudou.'
    guard = DeckProfileGuard(store=mapping.store, coordinator=mapping.coordinator)
    guard.bind_native(native)
    reason = guard.desktop_blocker({'deck_desktop': {}, 'service_owner': owner}, mapper_pid=os.getpid())
    if reason or lease_blockers(mapping.store.root) or mapping.read() != s:
        return reason or 'Controle reservado ou preferência alterada.'
    return ''


def _toggle_keyboard(native, owner):
    from .accessibility import PROPERTIES
    interface = 'org.kde.kwin.VirtualKeyboard'
    path = '/VirtualKeyboard'
    native.deadline = native.clock() + 2
    props = native.props(owner, path, interface)
    if (props.get('available') != 'true' or props.get('mode') not in ('1', '2')
            or props.get('visible') not in ('false', 'true')):
        raise ValueError('Habilite um teclado virtual no KDE para usar este atalho.')
    if props['visible'] == 'true':
        native.call([native.qdbus, owner, path, PROPERTIES + '.Set', interface, 'active', 'false'])
    else:
        native.call([native.qdbus, owner, path, interface + '.forceActivate'])


def run(token, *, keyboard_only=False):
    from ..actions.deck_mapping import DeckMapping, mapper_profile
    from .accessibility import NativeInput
    mapping = DeckMapping()
    s = _session(mapping, token, 'running' if keyboard_only else 'starting')
    native = NativeInput()
    if keyboard_only:
        if reason := _desktop_blocker(mapping, s, native):
            raise ValueError(reason)
        _toggle_keyboard(native, s['kwin'])
        return 0
    from ..actions.accessibility import save_object
    mapper_profile()
    nodes = _device_nodes()
    with ExitStack() as stack:
        outputs = [_virtual(stack, NAMES[0], [k for k in KEYS if k < PRIMARY]),
                   _virtual(stack, NAMES[1], [PRIMARY, SECONDARY], (0, 1, 6, 8))]
        if not _ready_outputs(outputs):
            raise ValueError('KWin não confirmou as duas saídas do perfil.')
        if mapping.read() != s:
            raise ValueError('Preferência alterada durante a partida.')
        from ..actions.deck_profile_guard import DeckProfileGuard
        if DeckProfileGuard._game_blocker(mapper_pid=os.getpid()):
            save_object(mapping.store.root / 'deck-map-yield.json', mapping.deferred_start(s))
            return 0
        handles = {}
        for key, (path, number) in nodes.items():
            fd = _fd(stack, path, os.O_RDONLY)
            info = os.fstat(fd)
            if not stat.S_ISCHR(info.st_mode) or info.st_rdev != number:
                raise ValueError('O dispositivo mudou durante a abertura.')
            if key == '02':
                ident = struct.unpack('=IHH', fcntl.ioctl(fd, 0x80084803, bytes(8)))
            else:
                ident = struct.unpack('=HHHH', fcntl.ioctl(fd, 0x80084502, bytes(8)))[:3]
            if ident != (3, 0x28de, 0x1205):
                raise ValueError('Identidade Valve diverge no descritor aberto.')
            handles[key] = fd
        layout = Layout()
        raw = handles['02']
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if select.select([raw], [], [], .15)[0]:
                packet = os.read(raw, 128)
                active_keys = sum(1 << bit for bit in (*BINDINGS, 13, 50))
                if valid_packet(packet) and not BUTTONS.unpack_from(packet, 8)[0] & active_keys:
                    break
        else:
            raise ValueError('Aguardando relatório neutro do Deck.')
        if nodes != _device_nodes():
            raise ValueError('O controle foi reenumerado durante a partida.')
        if _desktop_blocker(mapping, s, native):
            save_object(mapping.store.root / 'deck-map-yield.json', mapping.deferred_start(s))
            return 0
        for key in ('00', '01'):
            # EVIOCGRAB expires with this fd, including on crash. No HID feature
            # reports, USB reset, driver unbind, or persistent KWin changes.
            fcntl.ioctl(handles[key], 0x40044590, 1)
        _notify()
        heartbeat_check = time.monotonic() + 10
        last_osk = 0.
        keyboard = None
        emergency = None
        last_report = time.monotonic()
        while select.select([raw], [], [], 1)[0]:
            packet = os.read(raw, 128)
            if not packet:
                break
            now = time.monotonic()
            if not valid_packet(packet):
                if now - last_report > 1:
                    break
                continue
            last_report = now
            if now >= heartbeat_check:
                # A wedged monitor must not keep desktop ownership indefinitely.
                from ..actions.accessibility import read_object
                watched = read_object(mapping.store.root / 'watch-status.json') or {}
                if not 0 <= time.time() - watched.get('checked_at', 0) <= 35:
                    break
                heartbeat_check = now + 10
            bits, = BUTTONS.unpack_from(packet, 8)
            if bits & 0x6000 == 0x6000:
                emergency = now if emergency is None else emergency
                if now - emergency >= 1.5:
                    break
            else:
                emergency = None
            events, toggle = layout.translate(packet, now)
            if events:
                _emit(outputs, events)
            if toggle and now-last_osk >= .7 and (keyboard is None or keyboard.poll() is not None):
                keyboard = subprocess.Popen(
                    [sys.executable, '-m', 'folego.adapters.deck_mapper', token, 'keyboard'],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                last_osk = now
    return 1  # A lost stream or physical escape requires a fresh explicit selection.


if __name__ == '__main__':
    from .accessibility import ProbeError
    try:
        sys.exit(run(sys.argv[1], keyboard_only=sys.argv[2:] == ['keyboard']))
    except (ValueError, OSError, ProbeError) as exc:
        sys.exit(str(exc))
