"""Revalidate the user WirePlumber owner before recovering an incomplete ALSA probe."""
import configparser
import hashlib
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
                 state_home=None, tool=None):
        self.runner = runner
        self.proc_root, self.cgroup_root = Path(proc_root), Path(cgroup_root)
        self.state_home = Path(state_home) if state_home else Path.home() / '.local/state'
        self.tool = tool if tool is not None else _systemctl()

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
