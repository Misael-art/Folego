"""Short original cues with reversible volume on the verified Pulse sink."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import uuid

from .. import paths
from ..core.agent_deliveries import identity
from ..core.sessions import read_boot_id
from ..core.notification_tones import pcm, RATE
from ..safely.atomicfile import write_atomic
from .accessibility_recovery import DesktopRecovery

LOUD = round(65536 * .85)


class NotificationAudio:
    def __init__(self, *, env=None, run=subprocess.run, path=None, which=shutil.which):
        self.env = dict(os.environ if env is None else env)
        self.run, self.which = run, which
        self.path = Path(path) if path else paths.state_dir() / 'audio-volume.json'
        self.pulse = DesktopRecovery(None, runner=self._run, which=which)

    def _run(self, argv, *, timeout=3, env=None):
        return self.run(argv, env={**self.env, 'LC_ALL': 'C'}, capture_output=True, text=True, timeout=timeout)

    def _call(self, *args):
        result = self._run([self.which('pactl'), *args])
        if result.returncode: raise RuntimeError('Áudio não confirmado; não houve repetição')
        return result.stdout.strip()

    def _server(self):
        address = self.env.get('PULSE_SERVER', 'unix:' + str(Path(self.env.get('XDG_RUNTIME_DIR', '')) / 'pulse/native'))
        if not address.startswith('unix:/'): raise RuntimeError('Servidor local de áudio não identificado')
        path = Path(address[5:]); info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError('Servidor de áudio sem identidade local comprovada')
        return [str(path), info.st_dev, info.st_ino]

    def _sink(self, name):
        nodes = self.pulse._audio_nodes(self.which('pactl'), 'sink')
        matches = [n for n in nodes if n['name'] == name]
        if len(matches) != 1: raise RuntimeError('Saída de áudio desapareceu; volume preservado')
        node = matches[0]
        key = DesktopRecovery._audio_identity(node)
        key['serial'] = str(node.get('properties', {}).get('object.serial', ''))
        return dict(identity=key, channels=list(node['volume']),
                    volumes=[v['value'] for v in node['volume'].values()], mute=node['mute'])

    def _read(self):
        if self.path.is_symlink(): raise ValueError('Registro de áudio simbólico; preservado')
        try: fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError: return None
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('Registro de áudio sem propriedade comprovada')
            raw = stream.read(32769)
        if len(raw) > 32768: raise ValueError('Registro de áudio acima do limite; preservado')
        value = json.loads(raw)
        if (not isinstance(value, dict) or set(value) != {'schema', 'status', 'id', 'owner', 'server', 'sink', 'before', 'applied'}
                or type(value['schema']) is not int or value['schema'] != 1
                or value['status'] not in ('prepared', 'restored', 'user-changed')
                or not isinstance(value['id'], str) or len(value['id']) != 32
                or not isinstance(value['owner'], dict) or set(value['owner']) != {'pid', 'start', 'boot'}
                or type(value['owner']['pid']) is not int or type(value['owner']['start']) is not int
                or not isinstance(value['owner']['boot'], str)
                or not isinstance(value['server'], list) or len(value['server']) != 3
                or not isinstance(value['sink'], dict)):
            raise ValueError('Registro de áudio desconhecido; preservado')
        target = value['sink']
        if (set(target) != {'identity', 'channels', 'volumes', 'mute'} or not isinstance(target['identity'], dict)
                or set(target['identity']) != {'name', 'index', 'identity', 'serial'}
                or not isinstance(target['identity']['name'], str) or target['identity']['name'].startswith('-')
                or not isinstance(target['channels'], list) or not 1 <= len(target['channels']) <= 32):
            raise ValueError('Identidade da saída desconhecida; preservada')
        for key in ('before', 'applied'):
            state = value[key]
            if (not isinstance(state, dict) or set(state) != {'volumes', 'mute'} or type(state['mute']) is not bool
                    or not isinstance(state['volumes'], list) or len(state['volumes']) != len(target['channels'])
                    or any(type(v) is not int or not 0 <= v <= 655360 for v in state['volumes'])):
                raise ValueError('Volume anterior desconhecido; preservado')
        return value

    def _save(self, value):
        write_atomic(self.path, (json.dumps(value, sort_keys=True) + '\n').encode(), mode=0o600)

    def _restore(self, receipt):
        if receipt['owner']['boot'] != read_boot_id('/proc'):
            raise RuntimeError('Registro de outro boot; volume atual preservado')
        if self._server() != receipt['server']: raise RuntimeError('Servidor mudou; restauração de volume pendente')
        before, applied, target = receipt['before'], receipt['applied'], receipt['sink']
        now = self._sink(target['identity']['name'])
        if now['identity'] != target['identity'] or now['channels'] != target['channels']:
            raise RuntimeError('Saída mudou; restauração de volume pendente')
        changed = False
        # Respect a user's concurrent adjustment, independently per capability.
        for key, command in (('volumes', 'set-sink-volume'), ('mute', 'set-sink-mute')):
            current = self._sink(target['identity']['name'])
            if (current['identity'] != target['identity'] or current['channels'] != target['channels']
                    or self._server() != receipt['server']):
                raise RuntimeError('Saída mudou; restauração de volume pendente')
            if current[key] == before[key]: continue
            if current[key] != applied[key]: changed = True; continue
            args = [str(v) for v in before[key]] if key == 'volumes' else [str(int(before[key]))]
            self._call(command, target['identity']['name'], *args)
            if self._sink(target['identity']['name'])[key] != before[key]:
                raise RuntimeError('Restauração do volume não confirmada; registro preservado')
        receipt['status'] = 'user-changed' if changed else 'restored'; self._save(receipt)

    def perform(self, action, value=None):
        if action not in ('alert-play', 'alert-recover'): raise ValueError('Ação sonora desconhecida')
        if action == 'alert-recover' and not self.path.exists() and not self.path.is_symlink(): return ''
        tone = pcm(value['tone']) if action == 'alert-play' else None
        if not self.which('pactl') or (action == 'alert-play' and not self.which('paplay')):
            raise RuntimeError('Sons requerem pactl e paplay do PulseAudio/PipeWire')
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.parent.is_symlink(): raise ValueError('Diretório de áudio simbólico; preservado')
        fd = os.open(self.path.with_suffix('.lock'), os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('Lock de áudio desconhecido')
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError('Outro aviso sonoro está em andamento') from None
            prior = self._read()
            if prior and prior['status'] == 'prepared':
                owner = identity(prior['owner']['pid'])
                if (prior['owner']['pid'] != os.getpid() and owner and owner[2] == prior['owner']['start']
                        and read_boot_id('/proc') == prior['owner']['boot']):
                    raise RuntimeError('A alteração de volume ainda pertence a outro processo ativo')
                self._restore(prior)
            if action == 'alert-recover': return ''
            name = self._call('get-default-sink')
            sink = self._sink(name); server = self._server()
            if any(v > 655360 for v in sink['volumes']): raise ValueError('Volume da saída fora do limite conhecido')
            original = dict(volumes=sink['volumes'], mute=sink['mute'])
            applied = dict(volumes=[max(v, LOUD) for v in sink['volumes']], mute=False) if value.get('raise_volume', True) else original
            owner = identity(os.getpid())
            receipt = dict(schema=1, status='prepared', id=uuid.uuid4().hex,
                owner=dict(pid=os.getpid(), start=owner[2], boot=read_boot_id('/proc')),
                server=server, sink=sink, before=original, applied=applied)
            self._save(receipt)  # durable intent before volume or playback
            try:
                current = self._sink(name)
                if current != sink or self._server() != server or self._call('get-default-sink') != name:
                    raise RuntimeError('Saída mudou antes do aviso; nenhuma reprodução enviada')
                if original['volumes'] != applied['volumes']:
                    self._call('set-sink-volume', name, *map(str, applied['volumes']))
                if original['mute'] != applied['mute']: self._call('set-sink-mute', name, '0')
                current = self._sink(name)
                if (current['identity'] != sink['identity'] or current['volumes'] != applied['volumes']
                        or current['mute'] != applied['mute'] or self._server() != server):
                    raise RuntimeError('Volume do aviso não confirmado; reprodução não enviada')
                result = self.run([self.which('paplay'), '--raw', '--format=s16le', '--rate=' + str(RATE),
                    '--channels=1', '--volume=65536', '--device=' + name, '--client-name=Fôlego',
                    '--stream-name=Fôlego · ' + value['tone']], env=self.env, input=tone,
                    capture_output=True, timeout=5)
                if result.returncode: raise RuntimeError('Reprodução sonora não confirmada')
            finally:
                self._restore(receipt)
            return 'Som reproduzido; volume restaurado' if receipt['status'] == 'restored' else 'Som reproduzido; ajuste de volume do usuário preservado'
        finally: os.close(fd)

    def close(self):
        return True  # the single worker finishes playback/restoration before exit
