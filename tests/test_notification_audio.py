import copy
import json
import subprocess

import pytest

from folego.adapters.notification_audio import NotificationAudio, LOUD


class Pulse:
    def __init__(self, path):
        self.path = path
        self.volume = [14000, 21000]; self.mute = True
        self.calls = []; self.played = []
        self.fail = False; self.user_changes = False

    def run(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0].endswith('paplay'):
            self.played.append((self.volume[:], self.mute, kwargs['input']))
            if self.user_changes: self.volume = [18000, 18000]
            if self.fail: raise subprocess.TimeoutExpired('paplay', 5)
            return subprocess.CompletedProcess(argv, 0, b'', b'')
        if 'get-default-sink' in argv: value = 'qa_sink'
        elif 'list' in argv:
            value = json.dumps([dict(name='qa_sink', index=1, properties={'object.serial': '10'},
                mute=self.mute, volume={k:dict(value=v) for k,v in zip(('front-left','front-right'),self.volume)})])
        else:
            receipt = json.loads(self.path.read_text()); assert receipt['status'] == 'prepared'
            if 'set-sink-volume' in argv: self.volume = list(map(int, argv[3:]))
            if 'set-sink-mute' in argv: self.mute = argv[3] == '1'
            value = ''
        return subprocess.CompletedProcess(argv, 0, value, '')


def backend(tmp_path):
    path = tmp_path / 'audio.json'; pulse = Pulse(path)
    player = NotificationAudio(path=path, env={}, run=pulse.run, which=lambda n: '/qa/'+n)
    player._server = lambda: ['unix:/qa', 1, 2]
    return player, pulse


def test_loud_playback_restores_exact_channels_and_mute(tmp_path):
    player, pulse = backend(tmp_path)
    assert 'restaurado' in player.perform('alert-play', dict(tone='codex', raise_volume=True))
    assert pulse.played[0][:2] == ([LOUD, LOUD], False)
    assert pulse.volume == [14000, 21000] and pulse.mute
    assert json.loads(player.path.read_text())['status'] == 'restored'


def test_failed_or_timed_out_playback_restores_before_reporting(tmp_path):
    player, pulse = backend(tmp_path); pulse.fail = True
    with pytest.raises(subprocess.TimeoutExpired): player.perform('alert-play', dict(tone='low'))
    assert pulse.volume == [14000, 21000] and pulse.mute
    assert json.loads(player.path.read_text())['status'] == 'restored'


def test_concurrent_user_volume_is_preserved(tmp_path):
    player, pulse = backend(tmp_path); pulse.user_changes = True
    assert 'usuário preservado' in player.perform('alert-play', dict(tone='restored'))
    assert pulse.volume == [18000, 18000] and pulse.mute
    assert json.loads(player.path.read_text())['status'] == 'user-changed'


def test_unknown_receipt_is_preserved_and_blocks_effects(tmp_path):
    player, pulse = backend(tmp_path); raw = b'{"schema":99}'
    player.path.write_bytes(raw)
    with pytest.raises(ValueError): player.perform('alert-play', dict(tone='empty'))
    assert player.path.read_bytes() == raw and not pulse.calls


def test_opt_out_does_not_change_volume_or_mute(tmp_path):
    player, pulse = backend(tmp_path)
    player.perform('alert-play', dict(tone='web', raise_volume=False))
    assert pulse.played[0][:2] == ([14000, 21000], True)
    assert not any('set-sink-volume' in c or 'set-sink-mute' in c for c in pulse.calls)


def test_pending_interruption_is_reconciled_before_a_new_sound(tmp_path):
    player, pulse = backend(tmp_path)
    player.perform('alert-play', dict(tone='grok'))
    receipt = json.loads(player.path.read_text()); receipt['status'] = 'prepared'
    pulse.volume = receipt['applied']['volumes']; pulse.mute = False
    player.path.write_text(json.dumps(receipt))
    player.perform('alert-play', dict(tone='claude'))
    assert pulse.volume == [14000, 21000] and pulse.mute
