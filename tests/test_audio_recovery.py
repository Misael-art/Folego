"""Audio enumeration recovery uses disposable owners and never a host daemon."""
import json
import os
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from folego.adapters.audio_recovery import AudioRecoveryError, WirePlumberRecovery
from folego.adapters.deck_profiles import DeckProfiles, MIC_PROFILE

CARD = 'alsa_card.pci-0000_04_00.5-platform-acp5x_mach.0'


@pytest.fixture
def audio(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'
    process = proc / '123'
    process.mkdir(parents=True)
    (process / 'cmdline').write_bytes(b'/usr/bin/wireplumber\0')
    binary = tmp_path / 'wireplumber'
    binary.write_bytes(b'fake executable')
    (process / 'exe').symlink_to(binary)
    (process / 'stat').write_text('123 (wireplumber) S ' + '0 ' * 18 + '456\n')
    boot = proc / 'sys/kernel/random/boot_id'
    boot.parent.mkdir(parents=True)
    boot.write_text('12345678-1234-1234-1234-123456789abc')
    pcm = proc / 'asound/pcm'
    pcm.parent.mkdir()
    pcm.write_text('01-00: acp5x : capture 1\n')
    state = tmp_path / 'state'
    saved = state / 'wireplumber/default-profile'
    saved.parent.mkdir(parents=True)
    saved.write_text(f'[default-profile]\n{CARD}={MIC_PROFILE}\n')
    saved.chmod(0o600)
    group = f'/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/session.slice/wireplumber.service'
    members = tmp_path / 'cgroup' / group.lstrip('/') / 'cgroup.procs'
    members.parent.mkdir(parents=True)
    members.write_text('123\n')
    unit = Path('/usr/lib/systemd/user/wireplumber.service')
    resolve, read_bytes = Path.resolve, Path.read_bytes
    monkeypatch.setattr(Path, 'resolve', lambda self, **kw: self if self == unit else resolve(self, **kw))
    monkeypatch.setattr(Path, 'read_bytes', lambda self: b'official fixture unit' if self == unit else read_bytes(self))
    values = {'MainPID': '123', 'ActiveState': 'active', 'SubState': 'running',
              'FragmentPath': str(unit), 'ControlGroup': group, 'DropInPaths': ''}
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        return CompletedProcess(argv, 0, '\n'.join(f'{key}={value}' for key, value in values.items()), '')
    adapter = WirePlumberRecovery(runner=runner, proc_root=proc, cgroup_root=tmp_path / 'cgroup',
                                 state_home=state, tool='fixture-systemctl')
    monkeypatch.setattr(adapter, '_system_file', lambda path: True)
    return adapter, values, calls, saved, members


def test_known_incomplete_probe_is_actionable_without_changing_audio(audio, tmp_path):
    adapter, _, calls, _, _ = audio
    card = {'name': CARD, 'active_profile': 'off', 'properties': {'api.alsa.card': '1'},
            'profiles': {'off': {}, 'HiFi (Headphones, Mic)': {'available': False}}}
    sources = [{'name': 'mic-biglinux', 'mute': False}, {'name': 'echo-cancel-source', 'mute': False}]
    model = tmp_path / 'model'
    model.write_text('Jupiter')
    def runner(argv, **kwargs):
        payload = [card] if argv[-1] == 'cards' else sources
        return CompletedProcess(argv, 0, 'mic-biglinux' if argv[-1] == 'get-default-source' else json.dumps(payload), '')
    probe = DeckProfiles(runner=runner, model_path=model, audio_recovery=adapter)
    observed = probe.microphone()
    assert observed['state'] == 'fault' and observed['code'] == 'audio-enumeration-incomplete'
    assert all(command[2] == 'show' for command in calls)
    probe.restore('microphone', observed)
    assert calls[-1][2:] == ['restart', 'wireplumber.service']


@pytest.mark.parametrize('change', ['preference', 'external-card', 'external-source', 'pcm', 'drop-in', 'members'])
def test_ambiguous_or_shared_recovery_is_blocked_before_effect(audio, change):
    adapter, values, calls, saved, members = audio
    card = {'name': CARD, 'properties': {'api.alsa.card': '1'}}
    cards, sources = [card], [{'name': 'mic-biglinux'}]
    if change == 'preference':
        saved.write_text(f'[default-profile]\n{CARD}=off\n')
    elif change == 'external-card':
        cards.append({'name': 'usb', 'active_profile': 'output:analog-stereo'})
    elif change == 'external-source':
        sources.append({'name': 'alsa_input.usb'})
    elif change == 'pcm':
        (adapter.proc_root / 'asound/pcm').write_text('01-00: playback 1\n')
    elif change == 'drop-in':
        values['DropInPaths'] = '/home/fixture/custom.conf'
    else:
        members.write_text('123\n456\n')
    with pytest.raises(AudioRecoveryError):
        adapter.probe(card, cards, sources, MIC_PROFILE)
    assert all('restart' not in command for command in calls)


def test_changed_owner_and_untrusted_system_files_are_rejected(audio, tmp_path):
    adapter, values, calls, _, _ = audio
    owner = adapter.owner()
    (adapter.proc_root / '123/stat').write_text('123 (wireplumber) S ' + '0 ' * 18 + '789\n')
    with pytest.raises(AudioRecoveryError, match='mudou'):
        adapter.restart(owner)
    assert all('restart' not in command for command in calls)
    file = tmp_path / 'custom-unit'
    file.write_text('custom')
    file.chmod(0o666)
    assert not WirePlumberRecovery._system_file(file)


def test_real_daemon_is_unavailable_to_default_test_instances():
    with pytest.raises(AudioRecoveryError, match='indisponível'):
        WirePlumberRecovery().owner()


def test_oversized_native_probe_becomes_unknown_instead_of_aborting_the_monitor(tmp_path):
    from folego.adapters.accessibility import ProbeError
    probe = DeckProfiles()
    def oversized(*args):
        raise ProbeError('fonte excede orçamento de leitura')
    probe._pactl = oversized
    assert probe.microphone()['state'] == 'unknown'


@pytest.mark.parametrize('broken', [False, True])
def test_virtual_microphone_requires_the_entire_capture_chain(tmp_path, broken):
    sources = [{'name': 'mic-biglinux', 'mute': False, 'index': 3},
               {'name': 'echo-cancel-source', 'mute': False, 'index': 2},
               {'name': 'alsa_input.internal', 'mute': False, 'index': 1,
                'properties': {'device.name': CARD}}]
    outputs = [{'source': 99 if broken else 1, 'mute': False,
                'properties': {'node.name': 'echo-cancel-capture'}},
               {'source': 2, 'mute': False, 'properties': {'node.name': 'mic-biglinux-capture'}}]
    def runner(argv, **kwargs):
        if argv[-1] == 'get-default-source':
            payload = 'mic-biglinux'
        elif argv[-1] == 'cards':
            payload = json.dumps([{'name': CARD, 'active_profile': MIC_PROFILE,
                                  'profiles': {MIC_PROFILE: {'available': True, 'sources': 1}}}])
        else:
            payload = json.dumps(outputs if argv[-1] == 'source-outputs' else sources)
        return CompletedProcess(argv, 0, payload, '')
    probe = DeckProfiles(runner=runner)
    result = probe.microphone()
    assert result['state'] == ('unknown' if broken else 'healthy')
    if broken:
        assert 'cadeia' in result['detail']
