"""Reversible rendering preference for the community Codex Desktop launcher.

Other Web launchers and browsers have their own configuration owners.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

from .. import paths
from ..audit_profile import SUSPENDED, normal_effects
from ..orchestration.coordinator import Coordinator
from ..safely.atomicfile import write_atomic

LIMIT = 65536
HEADER = '# Codex Desktop Linux launch flags.'
BEGIN = '# BEGIN Folego software rendering'
END = '# END Folego software rendering'
FLAGS = ('--enable-gpu', '--use-gl=angle', '--use-angle=swiftshader')
SCOPE = ('Próximas aberturas pelo launcher que lê este arquivo do Codex Desktop. '
         'O launcher Web separado e outros perfis não são alterados.')


class RenderingError(RuntimeError):
    pass


class RenderingUnconfirmed(RenderingError):
    """The intent exists; the caller must report an uncertain result."""

    def __init__(self, message, *, operation_id=None):
        super().__init__(message)
        self.operation_id = operation_id


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _trusted(path, limit):
    # Never follow a link, including a link in a parent directory.
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise RenderingError('Caminho com link simbólico; configuração preservada')
    info = path.stat()
    parent = path.parent.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022 or parent.st_uid != os.getuid()
            or parent.st_mode & 0o022 or info.st_size > limit):
        raise RenderingError('Propriedade, permissões ou tamanho não comprovados')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid) != (
                info.st_dev, info.st_ino, info.st_mode, info.st_uid):
            raise RenderingError('Identidade do arquivo mudou durante a leitura')
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns):
            raise RenderingError('Arquivo mudou durante a leitura; preservado')
    if len(data) > limit:
        raise RenderingError('Configuração excede o limite de leitura')
    return data, stat.S_IMODE(info.st_mode)


def software_flags(raw):
    try:
        text = raw.decode('utf-8')
    except UnicodeError as exc:
        raise RenderingError('Configuração não é UTF-8; preservada') from exc
    if not text.startswith(HEADER + '\n') or BEGIN in text or END in text:
        raise RenderingError('Formato do launcher desconhecido ou bloco sem recibo')
    lines = []
    for line in text.splitlines():
        flag = line.strip()
        if flag and not flag.startswith('#'):
            if not flag.startswith('--') or any(ord(c) < 32 for c in flag):
                raise RenderingError('Flag desconhecida; configuração preservada')
            if flag.startswith(('--disable-software-rasterizer', '--use-vulkan')):
                raise RenderingError('Flag incompatível com software; revisão manual necessária')
            if flag.startswith(('--disable-gpu=', '--enable-gpu=')):
                raise RenderingError('Flag de GPU desconhecida; configuração preservada')
            if flag in ('--disable-gpu', '--enable-gpu'):
                continue
            if flag.startswith(('--use-gl', '--use-angle')):
                if flag not in ('--use-gl=angle', '--use-gl=desktop', '--use-gl=egl',
                                '--use-angle=gl', '--use-angle=swiftshader'):
                    raise RenderingError('Backend gráfico desconhecido; configuração preservada')
                continue
        lines.append(line)
    result = ('\n'.join(lines).rstrip('\n') + '\n\n' + BEGIN + '\n'
              + '\n'.join(FLAGS) + '\n' + END + '\n').encode()
    if len(result) > LIMIT:
        raise RenderingError('Configuração resultante excede o limite')
    return result


class CodexRendering:
    def __init__(self, *, target=None, state=None, coordinator=None):
        self.target = Path(target) if target else paths.xdg_config_home() / 'codex-desktop/electron-flags.conf'
        self.state = Path(state) if state else paths.state_dir() / 'codex-rendering.json'
        if not self.target.is_absolute() or not self.state.is_absolute():
            raise RenderingError('XDG precisa de caminhos absolutos')
        self.coordinator = coordinator or Coordinator()

    def _receipt(self):
        if not self.state.exists() and not self.state.is_symlink():
            return None
        try:
            raw, _ = _trusted(self.state, 256 * 1024)
            row = json.loads(raw)
            if (type(row['schema']) is not int or row['schema'] != 1
                    or row['target'] != str(self.target)
                    or str(uuid.UUID(row['operation_id'])) != row['operation_id']
                    or row['phase'] not in ('intent', 'applied', 'restoring', 'restored')
                    or type(row['mode']) is not int or row['mode'] & ~0o777
                    or row['mode'] & 0o022):
                raise ValueError('schema/identidade')
            original = base64.b64decode(row['before'], validate=True)
            if (len(original) > LIMIT or digest(original) != row['before_hash']
                    or digest(software_flags(original)) != row['after_hash']):
                raise ValueError('conteúdo/digest')
            return row
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise RenderingError('Recibo desconhecido ou inconsistente; nenhuma repetição') from exc

    def _save(self, row):
        for parent in self.state.parents:
            if parent.is_symlink():
                raise RenderingError('Diretório de recibos com link simbólico')
        self.state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Validate the state directory before creating or replacing a receipt.
        info = self.state.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise RenderingError('Diretório de recibos não confiável')
        write_atomic(self.state, json.dumps(row).encode(), mode=0o600)

    def status(self):
        raw, mode = _trusted(self.target, LIMIT)
        row = self._receipt()
        if row is None:
            software_flags(raw)  # Unknown formats never become an actionable default.
        current = digest(raw)
        enabled = bool(row and current == row['after_hash'])
        conflict = bool(row and (mode != row['mode']
                        or current not in (row['before_hash'], row['after_hash'])
                        or row['phase'] == 'applied' and not enabled
                        or row['phase'] == 'restored' and enabled))
        pending = bool(row and row['phase'] in ('intent', 'restoring'))
        state = ('conflict' if conflict else 'pending' if pending else
                 'software' if enabled else 'unchanged')
        return {'schema': 1, 'state': state, 'enabled': enabled,
                'operation_id': row['operation_id'] if row else None,
                'phase': row['phase'] if row else None,
                'can_apply': not conflict and not pending,
                'can_restore': bool(row and row['phase'] != 'restored' and not conflict),
                'message': ('Configuração mudou; revisão manual necessária.' if conflict else
                            'Operação pendente; conteúdo conferido. Consulte o ID antes de continuar.' if pending else
                            'Renderização por software configurada para as próximas aberturas.' if enabled else
                            'Renderização original preservada; software ainda não configurado.'),
                'scope': SCOPE, 'target': str(self.target)}

    def apply(self, *, restore=False):
        with self.coordinator.lock(wait=.2), normal_effects() as allowed:
            if not allowed:
                raise RenderingError(SUSPENDED)
            raw, mode = _trusted(self.target, LIMIT)
            row = self._receipt()
            if restore and row is None:
                raise RenderingError('Sem recibo de configuração para restaurar')
            if row and digest(raw) not in (row['before_hash'], row['after_hash']):
                raise RenderingError('Arquivo mudou desde a operação; nenhuma alteração')
            if row and (mode != row['mode']
                        or row['phase'] == 'applied' and digest(raw) != row['after_hash']
                        or row['phase'] == 'restored' and digest(raw) != row['before_hash']):
                raise RenderingError('Configuração ou permissões mudaram; nenhuma alteração')
            if not restore and (row is None or row['phase'] == 'restored'):
                after = software_flags(raw)
                row = {'schema': 1, 'operation_id': str(uuid.uuid4()), 'target': str(self.target),
                       'phase': 'intent', 'mode': mode, 'before': base64.b64encode(raw).decode(),
                       'before_hash': digest(raw), 'after_hash': digest(after)}
                self._save(row)  # durable intent AND original bytes before effect
            original = base64.b64decode(row['before'], validate=True)
            desired = original if restore else software_flags(original)
            if row['phase'] == 'restoring' and not restore:
                raise RenderingError('Restauração pendente; consulte/restaure antes de ativar')
            row['phase'] = 'restoring' if restore else 'intent'
            self._save(row)
            # Revalidate immediately before replacing the launcher's file.
            check, check_mode = _trusted(self.target, LIMIT)
            if check != raw or check_mode != mode:
                raise RenderingError('Configuração mudou durante a operação; preservada')
            try:
                if raw != desired:
                    write_atomic(self.target, desired, mode=row['mode'])
                confirmed, _ = _trusted(self.target, LIMIT)
                if confirmed != desired:
                    raise RenderingError('Leitura posterior não corresponde à intenção')
                row['phase'] = 'restored' if restore else 'applied'
                self._save(row)
                return {**self.status(), 'outcome': 'sucesso'}
            except (OSError, RenderingError) as exc:
                raise RenderingUnconfirmed('Resultado não confirmado; consultar antes de repetir',
                                          operation_id=row['operation_id']) from exc
