"""Reversible widget policy applied before plasmashell reads its layout."""
from __future__ import annotations

import base64
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from . import paths
from .actions.accessibility import save_object
from .orchestration import ActionPlan, ActionResult, Coordinator, Outcome, ResourceIdentity
from .safely.atomicfile import write_atomic

LAYOUT = 'plasma-org.kde.plasma.desktop-appletsrc'
OPTIONAL = frozenset(('org.phasezero.deckpanel', 'org.codex.quotapanel',
                      'org.biglinux.micnoise', 'br.com.biglinux.micnoise'))
TRAYS = ('org.kde.plasma.systemtray', 'org.kde.plasma.private.systemtray')
HOOK = Path('systemd/user/plasma-plasmashell.service.d/50-folego-basic-widgets.conf')
UNIT = 'plasma-plasmashell.service'
MARKER = '# X-Folego-Managed=basic-widgets-v1'
_SECTION = re.compile(r'(?:\[[^\[\]\r\n]+\])+')


def _groups(raw):
    groups = {(): []}
    current = ()
    for line in raw.decode('utf-8').splitlines(keepends=True):
        key = line.strip()
        if key.startswith('['):
            if not _SECTION.fullmatch(key):
                raise ValueError('grupo do layout Plasma ilegível')
            current = tuple(re.findall(r'\[([^\]]+)\]', key))
            if current in groups:
                raise ValueError('grupo duplicado no layout Plasma')
            groups[current] = [line]
        else:
            groups[current].append(line)
    return groups


def _key(lines, key):
    matches = [line for line in lines[1:] if '=' in line and line.split('=', 1)[0].strip() == key]
    if len(matches) > 1:
        raise ValueError('chave duplicada no layout Plasma: ' + key)
    return matches[0].partition('=')[2].rstrip('\r\n') if matches else None


def _replace(lines, key, value):
    for i, line in enumerate(lines[1:], 1):
        if line.partition('=')[0].strip() == key:
            lines[i] = key + '=' + value + ('\r\n' if line.endswith('\r\n') else '\n')
            return
    if not lines[-1].endswith('\n'):
        lines[-1] += '\n'
    lines.append(key + '=' + value + '\n')


def _scope(path):
    return (len(path) in (2, 4, 6) and path[0] == 'Containments' and
            path[1].isascii() and path[1].isdecimal() and
            all(path[i] == 'Applets' and path[i + 1].isascii() and path[i + 1].isdecimal()
                for i in range(2, len(path), 2)))


def _layout_changes(groups):
    removed = {}
    edits = {}
    for path, lines in groups.items():
        if not _scope(path):
            continue
        plugin = _key(lines, 'plugin')
        if len(path) >= 4 and plugin in OPTIONAL:
            if path[:-2] not in groups:
                raise ValueError('widget opcional sem painel identificado')
            removed[path] = plugin
            if len(path) == 4:
                _remove_token(edits, groups, (*path[:2], 'General'), 'AppletOrder', ';', path[-1])
        if plugin in TRAYS:
            general = (*path, 'General')
            if general in groups:
                extra = _key(groups[general], 'extraItems') or ''
                known = _key(groups[general], 'knownItems') or ''
                if (OPTIONAL & set(extra.split(','))) - set(known.split(',')):
                    raise ValueError('registro dos widgets opcionais na bandeja não comprovado')
            for key in ('extraItems', 'hiddenItems', 'shownItems'):
                for widget in sorted(OPTIONAL):
                    _remove_token(edits, groups, general, key, ',', widget)
    for path in (*removed, *(token[0] for token in edits)):
        for length in range(1, len(path) + 1):
            if (*path[:length], '$i') in groups:
                raise ValueError('grupo imutável na configuração Plasma')
    if ('$i',) in groups:
        raise ValueError('layout Plasma imutável')
    return removed, {where: (old, new) for where, (old, new) in edits.items() if old != new}


def _remove_token(edits, groups, path, key, separator, token):
    if path not in groups:
        return
    if _key(groups[path], key + '[$i]') is not None:
        raise ValueError('lista imutável no layout Plasma: ' + key)
    value = _key(groups[path], key)
    if value is None:
        return
    if '\\' in value:
        raise ValueError('lista com escapes no layout Plasma: ' + key)
    member = (path, key, separator)
    before, after = edits.get(member, (value, value))
    edits[member] = (before, separator.join(item for item in after.split(separator) if item != token))


def _encode(groups):
    return ''.join(line for lines in groups.values() for line in lines).encode()


def disable_layout(raw):
    groups = _groups(raw)
    removed, edits = _layout_changes(groups)
    affected = set(removed.values())
    for (path, key, separator), (old, new) in edits.items():
        _replace(groups[path], key, new)
        if key == 'extraItems':
            affected.update(set(old.split(separator)) - set(new.split(separator)))
    for path in tuple(groups):
        if any(path[:length] in removed for length in (4, 6)):
            del groups[path]
    return _encode(groups), sorted(affected)


def _restore_tokens(current, original, modified, separator):
    present = current.split(separator) if current else []
    before = original.split(separator)
    after = modified.split(separator)
    for index, item in enumerate(before):
        if item in after or item in present or not item:
            continue
        following = next((value for value in before[index + 1:] if value in present), None)
        if following is not None:
            present.insert(present.index(following), item)
        else:
            present.append(item)
    return separator.join(present)


def restore_layout(current, original):
    if current == disable_layout(original)[0]:
        return original
    groups, originals = _groups(current), _groups(original)
    removed, edits = _layout_changes(originals)
    # Validate the currently visible layout too, including immutable groups.
    _layout_changes(groups)
    for path, lines in originals.items():
        root = next((path[:length] for length in (4, 6) if path[:length] in removed), None)
        if root is None:
            continue
        parent = root[:-2]
        if parent not in groups or _key(groups[parent], 'plugin') != _key(originals[parent], 'plugin'):
            raise ValueError('painel original do widget mudou; backup preservado')
        if path in groups and groups[path] != lines:
            raise ValueError('posição original do widget foi reutilizada; backup preservado')
        if path not in groups:
            last = next(reversed(groups.values()))
            if last and not last[-1].endswith('\n'):
                last[-1] += '\n'
            groups[path] = lines.copy()
    for (path, key, separator), (old, new) in edits.items():
        if path not in groups:
            raise ValueError('configuração original do painel mudou; backup preservado')
        parent = path[:-1]
        if (_key(groups.get(parent, ()), 'plugin') != _key(originals.get(parent, ()), 'plugin')
                or _key(groups[path], key + '[$i]') is not None):
            raise ValueError('identidade do painel ou da bandeja mudou; backup preservado')
        merged = _restore_tokens(_key(groups[path], key), old, new, separator)
        _replace(groups[path], key, merged)
    return _encode(groups)


def _hook(executable):
    name = str(executable)
    if (not executable.is_absolute() or re.search(r'[\x00-\x1f"\\%$]', name)
            or not executable.name.startswith('python')):
        raise ValueError('executável do preparo dos widgets não comprovado')
    return (f'{MARKER}\n[Service]\n'
            f'ExecStartPre=-"{name}" -I -m folego startup basic-widgets-prepare\n').encode()


def ensure_hook(config, unit_dirs, *, coordinator=None, reload=None):
    from .basic_session import _snapshot, _bytes, _parents

    if not any((directory / UNIT).is_file() for directory in unit_dirs):
        return 'unsupported'
    target = config / HOOK
    desired = _hook(Path(sys.executable))
    before = _snapshot(target)
    if before['kind'] == 'file' and _bytes(before) == desired:
        return 'scheduled'
    if before['kind'] == 'file':
        line = _bytes(before).decode().splitlines()
        match = re.fullmatch(r'ExecStartPre=-"([^"]+)" -I -m folego startup basic-widgets-prepare',
                             line[-1]) if len(line) == 3 else None
        if not match or _bytes(before) != _hook(Path(match[1])):
            raise ValueError('drop-in do Plasma pertence a outra configuração')
    coordinator = coordinator or Coordinator()
    plan = ActionPlan('startup.plasma-widgets-hook', ResourceIdentity.path(target),
                      {'before': before, 'executable': sys.executable})

    def install(committed):
        if _snapshot(target) != before:
            return ActionResult(plan.action, Outcome.REFUSED, plan.operation_id,
                                target_key=str(target), reason='drop-in mudou após revisão')
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _parents(target)
        info = target.parent.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('diretório do drop-in fora da configuração privada')
        write_atomic(target, desired, mode=0o600)
        if reload is not None:
            reload()
        else:
            binary = shutil.which('systemctl')
            if not binary:
                raise OSError('gerenciador de serviços indisponível')
            subprocess.run([binary, '--user', 'daemon-reload'], check=True, timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ActionResult(plan.action, Outcome.OK, plan.operation_id, target_key=str(target),
                            reason='política programada no início do Plasma')

    outcome = coordinator.run(plan, install, wait=.5)
    if outcome.outcome != Outcome.OK:
        raise ValueError(f'{outcome.reason} · operação {outcome.operation_id}')
    return 'scheduled'


def _before_plasma():
    group = Path('/proc/self/cgroup').read_text().strip()
    prefix = f'0::/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/'
    if not group.startswith(prefix) or not group.endswith('/' + UNIT):
        return False
    entries = list(itertools.islice(Path('/proc').iterdir(), 8193))
    if len(entries) > 8192:
        return False
    for item in entries:
        if item.name.isdecimal():
            try:
                if item.stat().st_uid == os.getuid() and (item / 'comm').read_text().strip() == 'plasmashell':
                    return False
            except FileNotFoundError:
                continue
    return True


def _receipt(state):
    from .basic_session import _snapshot, _bytes, LIMIT

    saved = _snapshot(state, limit=131072)
    if saved['kind'] == 'absent':
        return None, None
    row = json.loads(_bytes(saved))
    if (saved['mode'] & 0o077 or not isinstance(row, dict) or type(row.get('schema')) is not int
            or row['schema'] != 1 or row.get('phase') not in ('intended', 'applied', 'restoring', 'restored')
            or str(uuid.UUID(row['operation_id'])) != row['operation_id']
            or not isinstance(row.get('widgets'), list)
            or any(widget not in OPTIONAL for widget in row['widgets'])
            or not re.fullmatch(r'[0-9a-f]{64}', row['expected_sha'])):
        raise ValueError('recibo dos widgets desconhecido')
    original = base64.b64decode(row['original'], validate=True)
    if len(original) > LIMIT or hashlib.sha256(original).hexdigest() != row.get('original_sha'):
        raise ValueError('backup dos widgets divergente')
    return row, original


def widget_status(config, state, enabled):
    from .basic_session import _snapshot, _bytes

    try:
        saved = _snapshot(config / HOOK)
        hook = saved['kind'] == 'file' and _bytes(saved) == _hook(Path(sys.executable))
        row, _ = _receipt(state)
        if hook and enabled:
            snapshot = _snapshot(config / LAYOUT)
            if snapshot['kind'] == 'file':
                original = _bytes(snapshot)
                replacement, _ = disable_layout(original)
                if row and row['phase'] == 'applied' and replacement != original:
                    return {'state': 'conflict', 'message': 'Widgets voltaram a aparecer; configuração preservada.'}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {'state': 'unknown', 'message': str(exc)}
    phase = row['phase'] if row else 'unconfigured'
    info = {'state': phase, 'targets': row['widgets'] if row else []}
    if phase in ('intended', 'restoring'):
        return {**info, 'message': 'Resultado dos widgets pendente · operação ' + row['operation_id']}
    if phase == 'applied' and enabled and hook:
        return {**info, 'message': 'Widgets opcionais retirados da configuração do Plasma.'}
    if hook and (enabled or phase == 'applied'):
        return {**info, 'state': 'scheduled',
                'message': ('Widgets opcionais serão desativados no próximo início do Plasma.' if enabled else
                            'Widgets anteriores serão restaurados no próximo início do Plasma.')}
    return {**info, 'message': ('Widgets serão programados em um Plasma suportado.' if enabled else
                                'Sem alteração programada para os widgets.')}


def prepare(*, config=None, state=None, enabled=None, before_plasma=_before_plasma):
    from .basic_session import _snapshot, _bytes, _file, LIMIT
    from .startup import preference

    folder = Path(config) if config else paths.xdg_config_home()
    state = Path(state) if state else paths.state_dir() / 'basic-widgets.json'
    target = folder / LAYOUT
    if not before_plasma():
        raise ValueError('preparo de widgets exige Plasma fora de execução na unit de início')
    with Coordinator().lock(wait=.5):
        enabled = preference()['basic_session'] if enabled is None else enabled
        old, original = _receipt(state)
        current = _snapshot(target)
        if current['kind'] != 'file' and old is None:
            return {'state': 'no-layout'}
        raw = _bytes(current)
        if old is not None and old['phase'] in ('intended', 'restoring'):
            if current['sha256'] != old['expected_sha']:
                raise ValueError('efeito dos widgets incerto; consulte operação ' + old['operation_id'])
            old['phase'] = 'applied' if old['phase'] == 'intended' else 'restored'
            save_object(state, old)
        if enabled:
            desired, affected = disable_layout(raw)
            if old is not None and old['phase'] == 'applied':
                if desired != raw:
                    raise ValueError('widgets reapareceram após a aplicação; disposição preservada')
                return {'state': 'applied', 'widgets': old['widgets']}
            original = raw
        else:
            if old is None or old['phase'] == 'restored':
                return {'state': 'restored'}
            desired = restore_layout(raw, original)
            affected = old['widgets']
        if desired == raw:
            if not enabled and old is not None:
                old['phase'] = 'restored'
                save_object(state, old)
            return {'state': 'no-change', 'widgets': affected}
        if len(desired) > LIMIT:
            raise ValueError('layout resultante excede o orçamento')
        expected = _file(desired, current['mode'])
        operation = str(uuid.uuid4())
        backup = _file(original)
        record = {'schema': 1, 'operation_id': operation, 'phase': 'intended' if enabled else 'restoring',
                  'original': backup['data'], 'original_sha': backup['sha256'],
                  'expected_sha': expected['sha256'], 'widgets': affected}
        save_object(state, record)
        if not before_plasma() or _snapshot(target) != current:
            raise ValueError('layout ou proprietário mudou após a intenção · ' + operation)
        write_atomic(target, desired, mode=current['mode'])
        if _snapshot(target) != expected:
            raise ValueError('alteração dos widgets sem confirmação · ' + operation)
        record['phase'] = 'applied' if enabled else 'restored'
        save_object(state, record)
        return {'state': record['phase'], 'widgets': affected, 'operation_id': operation}
