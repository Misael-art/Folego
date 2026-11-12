"""Reversible Plasma login policy. No processes are stopped or signalled.

XDG overrides and user unit masks affect future activation. Original files and
links stay in a private, durable receipt. Unknown launchers remain protected.
"""
from __future__ import annotations

import base64
import configparser
import hashlib
import itertools
import json
import os
from pathlib import Path
import stat
import uuid

from . import paths
from .actions.accessibility import save_object
from .orchestration import Coordinator
from .safely.atomicfile import fsync_dir, write_atomic

DESKTOPS = frozenset((
    'steam.desktop', 'steam-input.desktop', 'com.valvesoftware.Steam.desktop',
    'codex-desktop.desktop', 'discord.desktop', '9router.desktop',
    'phasezero-chatgpt-web.desktop', 'phasezero-quota-meter.desktop',
    'phasezero-tray.desktop', 'phasezero-vibe-code.desktop',
    'phasezero-vibe-code-boot.desktop', 'big-preload-user.desktop',
    'pamac-tray-plasma.desktop', 'msm_kde_notifier.desktop',
    'org.kde.kdeconnect.daemon.desktop', 'geoclue-demo-agent.desktop',
    'snap-userd-autostart.desktop', 'baloo_file.desktop', 'jdsp-gui.desktop',
))
UNITS = frozenset((
    'ai-memory.service', 'hermes-gateway.service', 'phasezero-ai-memory-watch.service',
    'phasezero-ai-memory-sync.timer', 'pz-chatgpt-web-launcher-health.timer',
    'phasezero-input-restore.service', 'phasezero-terminal-keyboard.service',
    'retrofe-input-recovery.service', 'codex-update-manager.service',
    'emulation-steam-centralizer.service', 'shelly-notifications.service',
    'linuxtoys-flatpak-update.timer', 'jamesdsp-autostart.service',
    'biglinux-welcome.service', 'biglinux-webapps.service',
    'biglinux-dolphin-baloo-sync.service', 'kde-baloo.service',
    'appimagelauncherd.service', 'swtpm.service', 'steamzero-core.socket',
))
ESSENTIAL = frozenset((
    'folego.desktop', 'kaccess.desktop', 'kglobalacceld.desktop',
    'org.kde.plasmashell.desktop', 'polkit-kde-authentication-agent-1.desktop',
    'powerdevil.desktop', 'pam_kwallet_init.desktop', 'org.fcitx.Fcitx5.desktop',
    'org.kde.plasma-fallback-session-restore.desktop', 'gmenudbusmenuproxy.desktop',
    'xembedsniproxy.desktop', 'xapp-sn-watcher.desktop', 'xdg-user-dirs.desktop',
    'spice-vdagent.desktop', 'spice-vdagent-autostart-kde.desktop',
))
LIMIT = 65536
MAX_ENTRIES = 64
MASK = {'kind': 'link', 'target': '/dev/null'}
SCOPE = ('Vale para as próximas ativações e o próximo login. Aplicativos abertos continuam '
         'em execução. Entrada nativa, áudio, rede, energia, Plasma e Fôlego são preservados. '
         'Serviços opcionais ficam indisponíveis por unit enquanto a opção estiver ligada.')


class BasicSessionError(ValueError):
    pass


def _parents(path):
    if not path.is_absolute() or '..' in path.parts:
        raise BasicSessionError('Caminho de configuração inválido')
    for parent in path.parents:
        if parent.is_symlink():
            raise BasicSessionError('Diretório com link simbólico; preservado')


def _snapshot(path, *, link=False, system=False):
    _parents(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {'kind': 'absent'}
    if info.st_uid not in ((0, os.getuid()) if system else (os.getuid(),)):
        raise BasicSessionError('Propriedade da configuração não comprovada: ' + path.name)
    if stat.S_ISLNK(info.st_mode) and link:
        return {'kind': 'link', 'target': os.readlink(path)}
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_size > LIMIT:
        raise BasicSessionError('Arquivo desconhecido, gravável por terceiros ou excessivo: ' + path.name)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(LIMIT + 1)
        after = os.fstat(stream.fileno())
    if (opened.st_dev, opened.st_ino, opened.st_uid) != (info.st_dev, info.st_ino, info.st_uid) or (
            opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(data) > LIMIT:
        raise BasicSessionError('Arquivo mudou durante a leitura: ' + path.name)
    return _file(data, stat.S_IMODE(info.st_mode))


def _file(data, mode=0o600):
    return {'kind': 'file', 'mode': mode, 'data': base64.b64encode(data).decode('ascii'),
            'sha256': hashlib.sha256(data).hexdigest()}


def _bytes(value):
    raw = base64.b64decode(value['data'], validate=True)
    if hashlib.sha256(raw).hexdigest() != value['sha256']:
        raise BasicSessionError('Original com hash divergente; preservado')
    return raw


def _ini(raw):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(raw.decode('utf-8'))
    return parser


def _set_key(raw, section, key, value):
    parser = _ini(raw)
    if parser.has_section('$i') or any(s.startswith(section + ']') for s in parser.sections()):
        raise BasicSessionError('Grupo imutável ou expandido; preservado')
    if parser.has_option(section, key) and parser[section][key].endswith('[$i]'):
        raise BasicSessionError('Preferência imutável; preservada')
    if parser.has_option(section, key + '[$i]') or parser.has_section(section + '[$i]'):
        raise BasicSessionError('Preferência imutável; preservada')
    lines = raw.decode('utf-8').splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.strip() == f'[{section}]'), None)
    replacement = f'{key}={value}\n'
    if start is None:
        return (raw.rstrip(b'\n') + f'\n[{section}]\n{replacement}'.encode()).lstrip(b'\n')
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith('[')), len(lines))
    match = next((i for i in range(start + 1, end)
                  if lines[i].split('=', 1)[0].strip() == key and '=' in lines[i]), None)
    if match is not None:
        lines[match] = replacement
    else:
        if lines and not lines[end - 1].endswith('\n'): lines[end - 1] += '\n'
        lines.insert(end, replacement)
    result = ''.join(lines).encode()
    if _ini(result)[section][key] != value or len(result) > LIMIT:
        raise BasicSessionError('Configuração resultante não confirmada')
    return result


class BasicSession:
    def __init__(self, *, config=None, state=None, system_config=None, unit_dirs=None):
        self.config = Path(config) if config else paths.xdg_config_home()
        self.state = Path(state) if state else paths.state_dir() / 'basic-session.json'
        self.system_config = tuple(Path(p) for p in (system_config if system_config is not None else
                                   os.environ.get('XDG_CONFIG_DIRS', '/etc/xdg').split(':')) if str(p))
        self.unit_dirs = tuple(Path(p) for p in (unit_dirs if unit_dirs is not None else
                               ('/etc/systemd/user', '/usr/local/lib/systemd/user', '/usr/lib/systemd/user')))

    def _allowed(self, path):
        return (path == self.config / 'ksmserverrc' or
                path.parent == self.config / 'autostart' and path.name in DESKTOPS or
                path.parent == self.config / 'systemd/user' and path.name in UNITS)

    def _receipt(self):
        snap = _snapshot(self.state)
        if snap['kind'] == 'absent': return None
        if snap['mode'] & 0o077:
            raise BasicSessionError('Recibo não é privado; preservado')
        # Receipts have a separate bounded budget for original configuration bytes.
        row = json.loads(_bytes(snap))
        if (type(row.get('schema')) is not int or row['schema'] != 1
                or row.get('phase') not in ('intended', 'applied', 'restoring', 'restored')
                or str(uuid.UUID(row['operation_id'])) != row['operation_id']
                or not isinstance(row.get('entries'), list) or len(row['entries']) > MAX_ENTRIES):
            raise BasicSessionError('Recibo desconhecido; nenhuma repetição')
        seen = set()
        for entry in row['entries']:
            target = Path(entry['path'])
            if not self._allowed(target) or str(target) in seen:
                raise BasicSessionError('Escopo do recibo desconhecido')
            seen.add(str(target))
            before, after = entry['before'], entry['after']
            for value in (before, after):
                if value['kind'] == 'file':
                    if (type(value['mode']) is not int or value['mode'] & ~0o777
                            or value['mode'] & 0o022 or len(_bytes(value)) > LIMIT):
                        raise BasicSessionError('Original inválido no recibo')
                elif value['kind'] == 'link':
                    if (target.name not in UNITS or not isinstance(value['target'], str)
                            or not value['target'] or len(value['target']) > 4096 or '\0' in value['target']):
                        raise BasicSessionError('Link fora de escopo no recibo')
                elif value != {'kind': 'absent'}:
                    raise BasicSessionError('Tipo desconhecido no recibo')
            expected = MASK if target.name in UNITS else _file(
                _set_key(_bytes(before) if before['kind'] == 'file' else b'',
                         'General' if target.name == 'ksmserverrc' else 'Desktop Entry',
                         'loginMode' if target.name == 'ksmserverrc' else 'Hidden',
                         'emptySession' if target.name == 'ksmserverrc' else 'true'),
                before.get('mode', 0o600))
            if after != expected:
                raise BasicSessionError('Efeito do recibo não corresponde ao catálogo')
        return row

    def _save(self, row):
        if len(json.dumps(row).encode()) > LIMIT:
            raise BasicSessionError('Backup excede 64 KiB; configuração preservada')
        _snapshot(self.state)
        save_object(self.state, row)

    def _policy(self, enabled=None):
        from .startup import preference
        row = preference()
        if enabled is not None:
            row['basic_session'] = enabled
            save_object(paths.config_dir() / 'startup.json', row)
        return row['basic_session']

    def _plan(self):
        entries, preserved = [], []
        roots = (self.config, *self.system_config)
        effective = {}
        for root in roots:
            folder = root / 'autostart'
            _parents(folder / 'entry')
            if not folder.exists(): continue
            listing = list(itertools.islice(folder.iterdir(), 257))
            if len(listing) > 256: raise BasicSessionError('Autostart excede 256 entradas')
            for path in sorted(listing):
                if path.suffix == '.desktop': effective.setdefault(path.name, path)
        for name, source in effective.items():
            if name in ESSENTIAL: continue
            raw = _snapshot(source, system=source.parent != self.config / 'autostart')
            cfg = _ini(_bytes(raw))['Desktop Entry']
            if (cfg.get('Hidden', 'false') == 'true' or
                    cfg.get('OnlyShowIn') and 'KDE' not in cfg['OnlyShowIn'].split(';') or
                    'KDE' in cfg.get('NotShowIn', '').split(';')): continue
            if name not in DESKTOPS:
                preserved.append(name); continue
            target = self.config / 'autostart' / name
            before = _snapshot(target)
            after = _file(_set_key(_bytes(before) if before['kind'] == 'file' else b'',
                                    'Desktop Entry', 'Hidden', 'true'), before.get('mode', 0o600))
            entries.append({'path': str(target), 'before': before, 'after': after,
                            'source': str(source), 'source_before': raw})
        for name in sorted(UNITS):
            target = self.config / 'systemd/user' / name
            before = _snapshot(target, link=True)
            if before == MASK: continue  # An existing manual mask belongs to the user.
            if before['kind'] == 'absent' and not any((p / name).exists() for p in self.unit_dirs):
                continue
            entries.append({'path': str(target), 'before': before, 'after': dict(MASK)})
        target = self.config / 'ksmserverrc'
        before = _snapshot(target)
        after = _file(_set_key(_bytes(before) if before['kind'] == 'file' else b'',
                              'General', 'loginMode', 'emptySession'), before.get('mode', 0o600))
        if after != before: entries.append({'path': str(target), 'before': before, 'after': after})
        if len(entries) > MAX_ENTRIES: raise BasicSessionError('Mais de 64 efeitos; lote recusado')
        return entries, preserved

    def status(self):
        enabled = self._policy()
        receipt = self._receipt()
        conflicts = []
        if receipt:
            for entry in receipt['entries']:
                current = _snapshot(Path(entry['path']), link=Path(entry['path']).name in UNITS)
                expected = entry['before'] if receipt['phase'] == 'restored' else entry['after']
                if current != expected: conflicts.append(Path(entry['path']).name)
        phase = receipt['phase'] if receipt else 'unconfigured'
        pending = phase in ('intended', 'restoring')
        configured = phase == 'applied' and not conflicts
        return {'ok': not conflicts and not pending, 'enabled': enabled, 'default_enabled': True,
                'configured': configured, 'state': 'conflict' if conflicts else phase,
                'operation_id': receipt['operation_id'] if receipt else None,
                'targets': [Path(e['path']).name for e in receipt['entries']] if receipt else [],
                'preserved': receipt.get('preserved', []) if receipt else [],
                'conflicts': conflicts, 'scope': SCOPE,
                'message': ('Configuração mudou; consulte o recibo antes de alterar.' if conflicts else
                            'Resultado pendente; consulte ou restaure pelo mesmo código.' if pending else
                            'Sessão básica configurada para as próximas ativações.' if configured else
                            'Configuração anterior restaurada.' if phase == 'restored' else
                            'Ligado por padrão; configuração ainda não aplicada.')}

    def configure(self, enabled=None, *, reconcile=False):
        with Coordinator().lock(wait=.2):
            receipt = self._receipt()
            if reconcile:
                if not receipt: return self.status()
                desired = 'before' if receipt['phase'] == 'restoring' else 'after'
                if receipt['phase'] not in ('intended', 'restoring'): return self.status()
                if not all(_snapshot(Path(e['path']), link=Path(e['path']).name in UNITS) == e[desired]
                           for e in receipt['entries']):
                    return {**self.status(), 'outcome': 'desconhecido'}
                receipt['phase'] = 'restored' if desired == 'before' else 'applied'
                self._save(receipt)
                self._policy(desired != 'before')
                return {**self.status(), 'outcome': 'sucesso'}
            chosen = self._policy() if enabled is None else enabled
            if type(chosen) is not bool: raise BasicSessionError('Preferência precisa ser booleana')
            if chosen and 'KDE' not in os.environ.get('XDG_CURRENT_DESKTOP', '').split(':'):
                raise BasicSessionError('Sessão KDE não comprovada; configuração preservada')
            if receipt and receipt['phase'] in ('intended', 'restoring') and chosen:
                return {**self.status(), 'outcome': 'desconhecido'}
            entries = []
            if receipt and receipt['phase'] != 'restored':
                entries = receipt['entries']
                for entry in entries:
                    current = _snapshot(Path(entry['path']), link=Path(entry['path']).name in UNITS)
                    if current not in (entry['before'], entry['after']) or (
                            receipt['phase'] == 'applied' and current != entry['after']):
                        raise BasicSessionError('Mudança externa; original e configuração preservados')
            if chosen:
                additions, preserved = self._plan()
                old = {e['path'] for e in entries}
                additions = [e for e in additions if e['path'] not in old]
                if receipt and receipt['phase'] == 'applied' and not additions:
                    return {**self.status(), 'outcome': 'sucesso'}
                entries = [*entries, *additions]
            else:
                preserved = []
            if len(entries) > MAX_ENTRIES: raise BasicSessionError('Lote excede 64 efeitos')
            row = {'schema': 1, 'operation_id': str(uuid.uuid4()),
                   'parent_id': receipt['operation_id'] if receipt else None,
                   'phase': 'intended' if chosen else 'restoring',
                   'entries': entries, 'preserved': preserved}
            # All preimages are durable before the first target is changed.
            self._save(row)
            self._policy(chosen)
            try:
                for entry in entries:
                    target = Path(entry['path'])
                    current = _snapshot(target, link=target.name in UNITS)
                    if current not in (entry['before'], entry['after']):
                        raise BasicSessionError('Alvo mudou antes da escrita')
                    desired = entry['after'] if chosen else entry['before']
                    if current == desired: continue
                    if chosen and 'source' in entry and current == entry['before']:
                        if _snapshot(Path(entry['source']), system=True) != entry['source_before']:
                            raise BasicSessionError('Fonte do autostart mudou; nenhuma repetição')
                    self._write(target, desired, current)
                row['phase'] = 'applied' if chosen else 'restored'
                self._save(row)
                return {**self.status(), 'outcome': 'sucesso'}
            except (OSError, ValueError) as exc:
                return {'ok': False, 'outcome': 'desconhecido', 'enabled': chosen,
                        'operation_id': row['operation_id'], 'state': row['phase'],
                        'message': str(exc) + '; consultar antes de repetir.', 'scope': SCOPE}

    def _write(self, target, desired, expected):
        _parents(target)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = target.parent.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise BasicSessionError('Diretório de destino não confiável')
        if _snapshot(target, link=target.name in UNITS) != expected:
            raise BasicSessionError('Alvo mudou no ato')
        if desired['kind'] == 'file':
            write_atomic(target, _bytes(desired), mode=desired['mode'])
        elif desired['kind'] == 'link':
            temporary = target.with_name('.folego-' + uuid.uuid4().hex)
            try:
                temporary.symlink_to(desired['target'])
                os.replace(temporary, target)
                fsync_dir(target.parent)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            target.unlink()
            fsync_dir(target.parent)
        if _snapshot(target, link=target.name in UNITS) != desired:
            raise BasicSessionError('Efeito não confirmado por leitura')
