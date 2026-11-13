"""Revalidate the user WirePlumber owner before recovering an incomplete ALSA probe."""
import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

from .accessibility import bounded_command, bounded_read
from ..core.sessions import read_boot_id


class AudioRecoveryError(RuntimeError):
    pass


def _systemctl():
    return shutil.which('systemctl')


class WirePlumberRecovery:
    unit = 'wireplumber.service'

    def __init__(self, *, runner=bounded_command, proc_root='/proc', cgroup_root='/sys/fs/cgroup',
                 state_home=None, tool=None, journal_tool=None):
        self.runner = runner
        self.proc_root, self.cgroup_root = Path(proc_root), Path(cgroup_root)
        self.state_home = Path(state_home) if state_home else Path.home() / '.local/state'
        self.tool = tool if tool is not None else _systemctl()
        self.journal_tool = journal_tool if journal_tool is not None else shutil.which('journalctl')

    def command(self, args, *, timeout=2):
        if not self.tool:
            raise AudioRecoveryError('systemd de usuário indisponível para reenumerar o áudio')
        try:
            answer = self.runner([self.tool, '--user', *args], timeout=timeout,
                                 env={**os.environ, 'LC_ALL': 'C'})
        except (OSError, subprocess.SubprocessError) as exc:
            raise AudioRecoveryError('resposta do gerenciador de áudio não confirmada') from exc
        if answer.returncode or len(answer.stdout) > 32768:
            raise AudioRecoveryError('gerenciador de áudio não confirmou a solicitação')
        return answer.stdout

    def owner(self):
        text = self.command(['show', self.unit, '--property=MainPID,ActiveState,SubState,FragmentPath,ControlGroup,DropInPaths'])
        value = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
        if value.get('DropInPaths') != '':
            raise AudioRecoveryError('customização da unit de áudio exige revisão manual')
        if value.get('ActiveState') != 'active' or value.get('SubState') != 'running':
            raise AudioRecoveryError('WirePlumber não está ativo; recuperação de enumeração indisponível')
        pid = int(value.get('MainPID', '0'))
        if pid <= 1:
            raise AudioRecoveryError('processo WirePlumber desconhecido')
        proc = self.proc_root / str(pid)
        fragment = Path(value.get('FragmentPath', '')).resolve(strict=True)
        if (str(fragment) not in ('/usr/lib/systemd/user/wireplumber.service',
                                  '/lib/systemd/user/wireplumber.service')
                or not self._system_file(fragment)):
            raise AudioRecoveryError('unit do gerenciador de áudio sem propriedade comprovada')
        argv = (proc / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
        executable = (proc / 'exe').resolve(strict=True)
        if (proc.stat().st_uid != os.getuid() or executable.name != 'wireplumber'
                or not self._system_file(executable)
                or argv not in ([b'/usr/bin/wireplumber'], [b'/usr/sbin/wireplumber'])):
            raise AudioRecoveryError('executável do WirePlumber divergente; revisar a unit')
        group = value.get('ControlGroup', '')
        expected = f'/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/'
        if not group.startswith(expected) or not group.endswith('/wireplumber.service') or '..' in group.split('/'):
            raise AudioRecoveryError('grupo do gerenciador de áudio não comprovado')
        members = (self.cgroup_root / group.lstrip('/') / 'cgroup.procs').read_text().split()
        if members != [str(pid)]:
            raise AudioRecoveryError('gerenciador de áudio possui outros processos; revisar propriedade')
        fields = bounded_read(proc / 'stat', 8192).rsplit(')', 1)[1].split()
        boot = read_boot_id(self.proc_root)
        if not boot:
            raise AudioRecoveryError('boot do gerenciador de áudio desconhecido')
        return {'pid': pid, 'start_ticks': int(fields[19]), 'boot_id': boot,
                'unit': self.unit, 'fragment': str(fragment),
                'fragment_sha256': hashlib.sha256(fragment.read_bytes()).hexdigest()}

    @staticmethod
    def _system_file(path):
        info = path.stat()
        return stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022

    def probe(self, card, cards, sources, expected_profile):
        file = self.state_home / 'wireplumber/default-profile'
        info = file.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022 or info.st_size > 65536):
            raise AudioRecoveryError('preferência persistida de áudio não comprovada')
        saved = configparser.RawConfigParser(delimiters=('=',), interpolation=None)
        saved.read_string(bounded_read(file, 65536))
        if saved.get('default-profile', card['name'], fallback=None) != expected_profile:
            raise AudioRecoveryError('perfil desligado por escolha ou preferência desconhecida')
        if any(row.get('active_profile') != 'off' for row in cards if row.get('name') != card['name']):
            raise AudioRecoveryError('outra placa de áudio em uso; reenumeração compartilhada bloqueada')
        if any(row.get('name') not in ('mic-biglinux', 'echo-cancel-source')
               and not str(row.get('name', '')).endswith('.monitor') for row in sources):
            raise AudioRecoveryError('outra entrada física presente; revisar o caminho de captura')
        number = card.get('properties', {}).get('api.alsa.card')
        if not isinstance(number, str) or not number.isdecimal() or int(number) > 31:
            raise AudioRecoveryError('identidade ALSA incompleta')
        prefix = f'{int(number):02d}-00:'
        pcm = bounded_read(self.proc_root / 'asound/pcm', 65536)
        if not any(line.startswith(prefix) and 'capture 1' in line for line in pcm.splitlines()):
            raise AudioRecoveryError('captura ALSA da placa não comprovada')
        return self.owner()

    def restart(self, expected_owner):
        if self.owner() != dict(expected_owner):
            raise AudioRecoveryError('responsável de áudio mudou antes da recuperação')
        self.command(['restart', self.unit], timeout=8)

    def _pipewire_owner(self):
        text = self.command(['show', 'pipewire.service', '--property=MainPID,ActiveState,SubState'])
        values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
        if values.get('ActiveState') != 'active' or values.get('SubState') != 'running':
            raise AudioRecoveryError('PipeWire ativo não comprovado')
        pid = int(values.get('MainPID', '0'))
        if pid <= 1:
            raise AudioRecoveryError('processo PipeWire desconhecido')
        proc = self.proc_root / str(pid)
        executable = (proc / 'exe').resolve(strict=True)
        argv = bounded_read(proc / 'cmdline', 8192).rstrip('\0').split('\0')
        if (proc.stat().st_uid != os.getuid() or executable.name != 'pipewire'
                or not self._system_file(executable)
                or argv not in (['/usr/bin/pipewire'], ['/usr/sbin/pipewire'])):
            raise AudioRecoveryError('identidade do PipeWire não comprovada')
        fields = bounded_read(proc / 'stat', 8192).rsplit(')', 1)[1].split()
        return {'pid': pid, 'start_ticks': int(fields[19])}

    def probe_missing_nodes(self, card, cards, sources, sinks, expected_profile):
        """Prove the login ALSA-busy failure while the intended HiFi profile is active."""
        owner = self.probe(card, cards, sources, expected_profile)
        if card.get('active_profile') != expected_profile:
            raise AudioRecoveryError('perfil interno mudou durante a consulta')
        if any(str(row.get('name', '')).startswith('alsa_output.') for row in sinks):
            raise AudioRecoveryError('saída física presente; revisar o uso de áudio')
        number = int(card['properties']['api.alsa.card'])
        alsa = self.proc_root / f'asound/card{number}'
        if bounded_read(alsa / 'id', 64).strip() != 'acp5x':
            raise AudioRecoveryError('identidade da placa ALSA divergente')
        for pcm in ('pcm0c', 'pcm0p', 'pcm1p'):
            if bounded_read(alsa / pcm / 'sub0/status', 1024).strip() != 'closed':
                raise AudioRecoveryError('PCM interno em uso; recuperação adiada')
        pipewire = self._pipewire_owner()
        if not self.journal_tool:
            raise AudioRecoveryError('histórico da falha de abertura indisponível')
        try:
            answer = self.runner([
                self.journal_tool, '--user', '--boot=' + owner['boot_id'].replace('-', ''),
                '--unit=pipewire.service', f'_PID={pipewire["pid"]}',
                '--output=json', '--no-pager', '--lines=64'], timeout=2,
                env={**os.environ, 'LC_ALL': 'C'})
        except (OSError, subprocess.SubprocessError) as exc:
            raise AudioRecoveryError('histórico da falha de abertura indisponível') from exc
        if answer.returncode or len(answer.stdout) > 65536:
            raise AudioRecoveryError('histórico de abertura do áudio incompleto')
        since = max(owner['start_ticks'], pipewire['start_ticks']) * 1000000 // os.sysconf('SC_CLK_TCK')
        events = {}
        for line in answer.stdout.splitlines():
            record = json.loads(line)
            if (record.get('_BOOT_ID') != owner['boot_id'].replace('-', '')
                    or record.get('_PID') != str(pipewire['pid'])
                    or record.get('_UID') != str(os.getuid())
                    or record.get('_SYSTEMD_USER_UNIT') != 'pipewire.service'):
                raise AudioRecoveryError('origem do histórico de áudio divergente')
            stamp = int(record['__MONOTONIC_TIMESTAMP'])
            message = record.get('MESSAGE')
            if not isinstance(message, str):
                raise AudioRecoveryError('registro de abertura desconhecido')
            if stamp < since or not any(text in message.lower() for text in (
                    'device or resource busy', 'dispositivo ou recurso está ocupado')):
                continue
            for key, text in (('capture', "hw:acp5x,0': capture open failed:"),
                              ('playback', "hw:acp5x,1': playback open failed:")):
                if text in message:
                    events.setdefault(key, stamp)
        if set(events) != {'capture', 'playback'}:
            raise AudioRecoveryError('falha de abertura ocupada não comprovada neste boot e responsáveis')
        if self.owner() != owner or self._pipewire_owner() != pipewire:
            raise AudioRecoveryError('responsável do áudio mudou durante a consulta')
        return owner, {'pipewire': pipewire, 'events': events}
