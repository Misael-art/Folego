import time
import uuid
from types import SimpleNamespace

import pytest

from folego.actions import deck_mapping as mapping
from folego.actions.accessibility import Store
from folego.actions.deck_profile_guard import DeckProfileGuard
from folego.core.deck_games import game_program


class Unit:
    def __init__(self):
        self.pid = 0
        self.effects = []

    def state(self, token):
        return self.pid

    def start(self, token, root):
        intent = mapping.read_object(root / 'deck-mapping.json')
        assert intent['stage'] == 'starting' and intent['token'] == token
        self.effects.append('start')
        self.pid = 123

    def stop(self, token):
        self.effects.append('stop')
        self.pid = 0


@pytest.fixture
def session(tmp_path, monkeypatch):
    u = Unit()
    obj = mapping.DeckMapping(Store(tmp_path / 'input'), unit=u)
    report = dict(schema=1, mono=time.monotonic(), backend='kwin', service_owner=':1.88',
                  boot_id=str(uuid.uuid4()), devices=[{'key': 'k', 'enabled': True}, {'key': 'p', 'enabled': True}],
                  deck_desktop=dict(display='portátil', roles={'k': 'keyboard','p': 'pointer'}, native_available=True))
    guard = SimpleNamespace(desktop_blocker=lambda *a, **kw: '', _game_blocker=lambda **kw: '',
                            _native=SimpleNamespace(collect=lambda: report.copy()))
    monkeypatch.setattr(mapping, 'resident', lambda: True)
    monkeypatch.setattr(mapping, 'mapper_profile', lambda: True)
    return obj, report, guard, u


def start(obj, report, guard):
    obj.select('phasezero')
    obj.tick(report, guard)
    report['mono'] = time.monotonic()
    obj.tick(report, guard)


def test_switch_persist_yield_resume_and_release(session):
    obj, report, guard, unit = session
    obj.tick(report, guard)
    assert unit.effects == [] and not obj.receipt.exists()
    start(obj, report, guard)
    assert obj.active and obj.read()['choice'] == 'phasezero'
    guard._game_blocker = lambda **kw: 'ES-DE'
    obj.yield_to_game(guard)
    assert unit.effects == ['start', 'stop'] and not obj.active
    assert obj.read()['choice'] == 'phasezero'
    obj.tick(report, guard)
    report['mono'] = time.monotonic()
    obj.tick(report, guard)
    obj.select('steam')
    obj.tick(report, guard)
    assert unit.effects == ['start', 'stop'] * 2
    assert mapping.DeckMapping(obj.store).read()['choice'] == 'steam'


def test_unknown_or_changed_owner_never_starts_and_crash_never_replays(session):
    obj, report, guard, unit = session
    guard._native.collect = lambda: {**report, 'service_owner': ':1.99'}
    start(obj, report, guard)
    assert not unit.effects
    guard._native.collect = lambda: report.copy()
    start(obj, report, guard)
    assert unit.effects == ['start']
    unit.pid = 0
    for _ in range(4):
        report['mono'] = time.monotonic()
        obj.tick(report, guard)
    assert obj.read()['stage'] == 'failed' and unit.effects == ['start']


@pytest.mark.parametrize('comm,env', [
    ('AppRun', b'APPIMAGE=/emu/Eden-NX2-2026.10.29-x86_64.AppImage'),
    ('sandbox', b'FLATPAK_ID=org.azahar_emu.Azahar'),
    ('unknown', b'SteamAppId=1111'), ('RocketLauncher.', b''),
    ('python3', b''), ('quiver-launcher', b''), ('SharpEmu', b'')])
def test_launch_identities(tmp_path, comm, env):
    p = tmp_path / '22'
    p.mkdir()
    (p/'comm').write_text(comm)
    (p/'cmdline').write_bytes(b'python3\0/bin/steamzero-launcher\0' if comm == 'python3'
                              else b'C:\\Emulation\\RocketLauncher.exe\0' if comm.startswith('Rocket')
                              else b'/tmp/AppRun\0')
    (p/'environ').write_bytes(env)
    assert DeckProfileGuard._game_blocker(tmp_path)


def test_desktop_tools_and_installer_are_not_games():
    for name in ('dolphin', 'steam-rom-manager', 'EmuDeck.AppImage', 'terminal64.exe', 'steamzero-core'):
        assert not game_program(name)
    assert game_program('Dolphin.AppImage')


def test_phasezero_reports_chords_trackpads_and_key_release():
    import struct
    from folego.adapters.deck_mapper import Layout, valid_packet
    layout = Layout()
    data = bytearray(64)
    data[:4] = b'\x01\x00\x09\x38'
    assert valid_packet(data) and not valid_packet(data[:-1])
    def move(bits, x=0):
        struct.pack_into('<Q', data, 8, bits)
        struct.pack_into('<h', data, 20, x)
        return layout.translate(data, time.monotonic())
    assert move((1<<13) | (1<<7))[0] == [(1, 29, 1), (1, 47, 1)]
    assert move(1<<7)[0] == []
    assert move(0)[0] == [(1, 47, 0), (1, 29, 0)]
    assert move(1<<50)[1]
    assert move(1<<50) == ([], False)
    move(1<<20)
    assert (2, 0, 10) in move(1<<20, 1550)[0]
    assert move(1<<18)[0] == [(1, 272, 1)]
    assert move(0)[0] == [(1, 272, 0)]
    assert move(1<<41)[0] == [(1, 125, 1)]


def test_mapper_unit_uses_notify_and_never_stops_foreign_unit(monkeypatch):
    calls = []
    token = str(uuid.uuid4())
    def run(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='LoadState=loaded\nTransient=no\n')
    monkeypatch.setattr(mapping, 'bounded_command', run)
    u = mapping.MapperUnit()
    u.start(token, None)
    assert '--service-type=notify' in calls[0] and 'folego.adapters.deck_mapper' in calls[0]
    with pytest.raises(ValueError, match='Identidade'):
        u.stop(token)
    assert len(calls) == 2 and 'stop' not in calls[-1]


def test_catalog_future_emulator_can_be_added_and_removed(fake_home):
    obj = mapping.DeckMapping()
    assert not obj.catalog()['additional']
    assert 'future-player' in obj.catalog(add='Future-Player')['additional']
    proc = fake_home/'proc'/'321'
    proc.mkdir(parents=True)
    (proc/'comm').write_text('future-player')
    (proc/'environ').write_bytes(b'')
    assert DeckProfileGuard._game_blocker(proc.parent)
    obj.catalog(remove='future-player')
    assert DeckProfileGuard._game_blocker(proc.parent) == ''
    with pytest.raises(ValueError):
        obj.catalog(add='python')


def test_cooperating_launcher_releases_unopened_gate_on_mapper_refusal(fake_home, monkeypatch):
    import sys
    from folego.actions import input_lease
    from folego.actions.accessibility import directory, read_object
    def occupied(self, s):
        raise ValueError('mapeador ocupado')
    monkeypatch.setattr(mapping.DeckMapping, 'release_for_lease_locked', occupied)
    mark = fake_home/'started'
    with pytest.raises(ValueError, match='ocupado'):
        input_lease.run('test-mapper', [sys.executable, '-c', f'open({str(mark)!r}, "w").close()'])
    assert not mark.exists()
    assert [read_object(p)['state'] for p in (directory()/'leases').glob('*.json')] == ['released']
