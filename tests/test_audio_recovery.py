"""Audio enumeration recovery uses disposable owners and never a host daemon."""
import json
import os
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired

import pytest

from folego.adapters.audio_recovery import AudioRecoveryError, WirePlumberRecovery
from folego.adapters.deck_profiles import DeckProfiles, MIC_PROFILE, ProfileUnknown

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


@pytest.fixture
def busy_audio(audio, tmp_path):
    adapter, values, calls, saved, members = audio
    pipewire = adapter.proc_root / '124'
    pipewire.mkdir()
    (pipewire / 'cmdline').write_bytes(b'/usr/bin/pipewire\0')
    binary = tmp_path / 'pipewire'
    binary.write_bytes(b'fixture pipewire')
    (pipewire / 'exe').symlink_to(binary)
    (pipewire / 'stat').write_text('124 (pipewire) S ' + '0 ' * 18 + '400\n')
    alsa = adapter.proc_root / 'asound/card1'
    alsa.mkdir()
    (alsa / 'id').write_text('acp5x\n')
    for name in ('pcm0c', 'pcm0p', 'pcm1p'):
        status = alsa / name / 'sub0/status'
        status.parent.mkdir(parents=True)
        status.write_text('closed\n')
    boot = (adapter.proc_root / 'sys/kernel/random/boot_id').read_text().replace('-', '')
    records = []
    for device, direction in ((0, 'capture'), (1, 'playback')):
        records.append({'_BOOT_ID': boot, '_PID': '124', '_UID': str(os.getuid()),
                        '_SYSTEMD_USER_UNIT': 'pipewire.service',
                        '__MONOTONIC_TIMESTAMP': '50000000',
                        'MESSAGE': f"spa.alsa: '_ucm0001.hw:acp5x,{device}': {direction} open failed: Device or resource busy"})
    journal = {'returncode': 0, 'text': None}
    adapter.journal_tool = 'fixture-journalctl'
    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[0] == 'fixture-journalctl':
            if journal.get('timeout'):
                raise TimeoutExpired(argv, 2)
            text = journal['text']
            if text is None:
                text = '\n'.join(json.dumps(row) for row in records)
            return CompletedProcess(argv, journal['returncode'], text, '')
        current = {**values, 'MainPID': '124'} if argv[3] == 'pipewire.service' else values
        return CompletedProcess(argv, 0, '\n'.join(f'{key}={value}' for key, value in current.items()), '')
    adapter.runner = runner
    card = {'name': CARD, 'active_profile': MIC_PROFILE, 'properties': {'api.alsa.card': '1'},
            'profiles': {MIC_PROFILE: {'available': True, 'sources': 1}}}
    sources = [{'name': 'mic-biglinux', 'mute': False}, {'name': 'echo-cancel-source', 'mute': False}]
    sinks = [{'name': 'auto_null'}]
    model = tmp_path / 'model'
    model.write_text('Jupiter')
    def pactl(argv, **kwargs):
        if argv[-1] == 'get-default-source':
            return CompletedProcess(argv, 0, 'mic-biglinux', '')
        payload = {'cards': [card], 'sources': sources, 'sinks': sinks}[argv[-1]]
        return CompletedProcess(argv, 0, json.dumps(payload), '')
    probe = DeckProfiles(runner=pactl, model_path=model, audio_recovery=adapter)
    return probe, adapter, card, sources, sinks, records, journal, calls


@pytest.mark.parametrize('language', ['english', 'portuguese'])
def test_active_hifi_missing_nodes_after_busy_is_recoverable(busy_audio, language):
    probe, adapter, card, sources, sinks, records, journal, calls = busy_audio
    if language == 'portuguese':
        for row in records:
            row['MESSAGE'] = row['MESSAGE'].replace('Device or resource busy', 'Dispositivo ou recurso está ocupado')
    observed = probe.microphone()
    assert observed['state'] == 'fault'
    assert observed['code'] == 'audio-nodes-missing-after-busy'
    assert observed['identity']['active'] == MIC_PROFILE
    assert observed['identity']['busy_evidence']['pipewire'] == {'pid': 124, 'start_ticks': 400}
    assert not any('restart' in command for command in calls)
    probe.restore('microphone', observed)
    assert sum('restart' in command for command in calls) == 1


@pytest.mark.parametrize('change', [
    'capture-open', 'playback-open', 'pcm-absent', 'card-id', 'physical-sink',
    'physical-source', 'external-card', 'mute', 'default', 'saved-profile',
    'stale-wireplumber', 'stale-pipewire', 'boot', 'pid', 'uid', 'unit',
    'only-capture-error', 'wrong-card-error', 'different-error',
    'journal-denied', 'journal-oversized', 'journal-malformed', 'journal-timeout',
])
def test_missing_nodes_without_complete_current_busy_evidence_stays_unknown(busy_audio, change):
    probe, adapter, card, sources, sinks, records, journal, calls = busy_audio
    alsa = adapter.proc_root / 'asound/card1'
    if change == 'capture-open':
        (alsa / 'pcm0c/sub0/status').write_text('state: RUNNING\nowner_pid: 300\n')
    elif change == 'playback-open':
        (alsa / 'pcm1p/sub0/status').write_text('state: PREPARED\nowner_pid: 300\n')
    elif change == 'pcm-absent':
        (alsa / 'pcm0p/sub0/status').unlink()
    elif change == 'card-id':
        (alsa / 'id').write_text('external\n')
    elif change == 'physical-sink':
        sinks.append({'name': 'alsa_output.internal'})
    elif change == 'physical-source':
        sources.append({'name': 'alsa_input.other'})
    elif change == 'external-card':
        original = probe.runner
        def runner(argv, **kwargs):
            if argv[-1] == 'cards':
                return CompletedProcess(argv, 0, json.dumps([card, {'name': 'usb', 'active_profile': 'on'}]), '')
            return original(argv, **kwargs)
        probe.runner = runner
    elif change == 'mute':
        sources[0]['mute'] = True
    elif change == 'default':
        original = probe.runner
        def runner(argv, **kwargs):
            return (CompletedProcess(argv, 0, 'external', '') if argv[-1] == 'get-default-source'
                    else original(argv, **kwargs))
        probe.runner = runner
    elif change == 'saved-profile':
        (adapter.state_home / 'wireplumber/default-profile').write_text(f'[default-profile]\n{CARD}=off\n')
    elif change in ('stale-wireplumber', 'stale-pipewire'):
        pid = '123' if change == 'stale-wireplumber' else '124'
        name = 'wireplumber' if pid == '123' else 'pipewire'
        (adapter.proc_root / pid / 'stat').write_text(f'{pid} ({name}) S ' + '0 ' * 18 + '999999\n')
    elif change in ('boot', 'pid', 'uid', 'unit'):
        key = {'boot': '_BOOT_ID', 'pid': '_PID', 'uid': '_UID', 'unit': '_SYSTEMD_USER_UNIT'}[change]
        records[0][key] = 'other'
    elif change == 'only-capture-error':
        records.pop()
    elif change == 'wrong-card-error':
        records[0]['MESSAGE'] = records[0]['MESSAGE'].replace('hw:acp5x', 'hw:usb')
    elif change == 'different-error':
        records[0]['MESSAGE'] = records[0]['MESSAGE'].replace('Device or resource busy', 'Permission denied')
    elif change == 'journal-denied':
        journal['returncode'] = 1
    elif change == 'journal-oversized':
        journal['text'] = 'x' * 65537
    elif change == 'journal-timeout':
        journal['timeout'] = True
    else:
        journal['text'] = '{'
    assert probe.microphone()['state'] == 'unknown'
    assert not any('restart' in command for command in calls)


def test_device_opened_between_observation_and_effect_blocks_restart(busy_audio):
    probe, adapter, card, sources, sinks, records, journal, calls = busy_audio
    observed = probe.microphone()
    assert observed['state'] == 'fault'
    (adapter.proc_root / 'asound/card1/pcm0c/sub0/status').write_text('state: RUNNING\n')
    with pytest.raises(ProfileUnknown, match='mudou antes'):
        probe.restore('microphone', observed)
    assert not any('restart' in command for command in calls)
