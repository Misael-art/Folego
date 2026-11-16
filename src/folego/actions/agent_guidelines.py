"""Bounded discovery and additive, reversible agent instructions. No agent is run.

The private receipt owns only our inserted fragment. Restoration merges around
that fragment, including later personal edits. Pending writes require readback
reconciliation; a periodic sync never replays an uncertain operation.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import stat
import uuid

from .. import paths
from ..adapters.accessibility import bounded_read
from ..basic_session import _snapshot as _read_snapshot, _bytes, _file
from ..orchestration import Coordinator
from ..safely.atomicfile import write_atomic, fsync_dir
from .accessibility import private_path, read_object, save_object

BEGIN = b'<!-- BEGIN FOLEGO HOST CARE v1 -->'
END = b'<!-- END FOLEGO HOST CARE v1 -->'
BODY = '''## Uso cuidadoso dos recursos do host

- Priorize a estabilidade da sessão. Antes de builds, suítes longas, instalações, extrações, cópias grandes, indexações, modelos locais ou VMs, meça CPU/carga e PSI, MemAvailable, atividade de swap, pressão de I/O, espaço no destino e nos temporários e temperatura com os limites do sensor. Inspecione concorrentes por RSS e comando completo e estime pico de RAM, saída em disco e paralelismo. CPU baixa ou prioridade baixa não provam ausência de outro build.
- Uma carga pesada por vez no host, contando outros IDEs, CLIs e agentes. Comece com um job; no máximo dois com margem medida e se o wrapper permitir. Serialize builds, suítes, VMs e QA; delegação não autoriza multiplicar cargas locais. nice/ionice não limitam consumo.
- Reserve RAM depois do pico estimado e espaço persistente além das saídas, staging e verificação. No Jupiter com cerca de 14,5 GiB compartilhados com GPU, preserve o maior entre 4 GiB e 25% de RAM disponível, e 10 GiB de disco além da saída. Em outro host, dimensione uma reserva conservadora antes da carga. /tmp e /run/user podem ser tmpfs: use temporários privados em disco e ambientes já gerenciados pelo projeto, com retenção limitada.
- Adie carga pesada com swap-in/out contínuo, PSI sustentada, pouca margem ou temperatura a menos de 10 °C do trip passivo. No Jupiter, 90 °C é ponto preventivo para adiar carga, não diagnóstico da causa dos cortes. Medição ou limite desconhecido exige obter evidência antes da carga; swap apenas ocupado não prova pressão.
- Reavalie a cada 15–30 s durante operações longas ou por telemetria equivalente. Com pressão crescente, reduza lote/jobs ou pause somente trabalho próprio quando seguro, antes de esgotar a reserva ou se aproximar do limite térmico. Preserve outras tarefas e continue trabalho leve independente enquanto aguarda margem.
- Não crie folga encerrando agentes, daemons, apps, rede ou sessão, limpando caches compartilhados ou dados pessoais. Não use stress, enchimento de RAM/disco, descarga ou aquecimento como QA no host físico. Sem instalações globais por conveniência. Encerre somente filhos temporários próprios identificados e acompanhados; preserve evidência e recuperação do trabalho útil.
- Execute os checks pertinentes em lotes proporcionais ao risco e registre ambiente, limites e resultados; não afrouxe gates para obter verde. Propague esta orientação ao criar novos perfis de agentes, conferindo o arquivo global realmente carregado. Esta orientação não amplia grants nem substitui contratos do projeto ou limites impostos pelo sistema.
'''
BLOCK = BEGIN + b'\n' + BODY.encode() + END + b'\n'
LEGACY_BEGIN = b'<!-- BEGIN HOST RESOURCE CHECK -->'
LEGACY_END = b'<!-- END HOST RESOURCE CHECK -->'
LEGACY_SHA = 'daec1f224f6b2112bd955d6e8a23494447e0f7819fd3384d9826ccaddc22dcf2'
MAX_TARGETS = 64
MAX_RECEIPT = 2 * 1024 * 1024
HEADERS = {
    'cursor': b'---\ndescription: Cuidados com os recursos do host\nalwaysApply: true\n---\n\n',
    'continue': b'---\nname: Cuidados com os recursos do host\nalwaysApply: true\n---\n\n',
    'code-local': b"---\nname: Cuidados com os recursos do host\napplyTo: '**'\n---\n\n",
}
SCOPE = ('Acrescenta ou retira somente a orientação identificada do Fôlego nos agentes '
         'compatíveis deste usuário. Preserva diretrizes pessoais. Novas sessões/recargas '
         'recebem a orientação; ela não impõe limites de recursos pelo sistema.')


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _snapshot(path):
    value = _read_snapshot(path)
    if value['kind'] == 'file' and path.lstat().st_nlink != 1:
        raise ValueError('Diretrizes com múltiplos links; preservadas')
    return value


def _listing(folder, limit=64):
    if not folder.exists():
        return []
    private_path(folder / 'entry')
    rows = list(itertools.islice(folder.iterdir(), limit + 1))
    if len(rows) > limit:
        raise ValueError('Descoberta excede orçamento: ' + folder.name)
    return sorted(rows)


class AgentGuidelines:
    def __init__(self):
        self.home = Path.home()
        self.config = paths.config_dir() / 'agent-guidelines.json'
        self.state = paths.state_dir() / 'agent-guidelines.json'

    def _catalog(self, *, discover=True):
        h = self.home
        candidates = [
            ('codex', h / '.codex', 'AGENTS.md'),
            ('codex-web', h / '.local/share/phasezero/chatgpt-web/codex-home', 'AGENTS.md'),
            ('claude', h / '.claude', 'CLAUDE.md'),
            ('opencode', paths.xdg_config_home() / 'opencode', 'AGENTS.md'),
            ('antigravity', h / '.gemini', 'GEMINI.md'),
            ('hermes', h / '.hermes', 'SOUL.md'),
            ('cursor', h / '.cursor', 'rules/host-care.mdc'),
            ('continue', h / '.continue', 'rules/host-care.md'),
            ('prime', h / '.prime/agent', 'AGENTS.md'),
            ('zcode', h / '.zcode', 'AGENTS.md'),
            ('qoder', h / '.qoder', 'AGENTS.md'),
            ('copilot', h / '.copilot', 'copilot-instructions.md'),
            ('code-local', paths.xdg_config_home() / 'Code/User', 'prompts/host-care.instructions.md'),
        ]
        profiles = h / '.local/share/phasezero/codex'
        for profile in _listing(profiles, 32):
            if profile.is_dir():
                candidates.append(('codex-profile', profile / 'native', 'AGENTS.md'))
        result = {}
        for client, root, filename in candidates:
            # A configured client is evidence; never recurse into projects or caches.
            present = root.is_dir()
            if client == 'copilot':
                present = present or (paths.xdg_config_home() / 'Code/User').is_dir()
            if client == 'continue':
                present = present or any(p.name.startswith('continue.continue-')
                                         for editor in ('.vscode', '.cursor')
                                         for p in _listing(h / editor / 'extensions', 256))
            if discover and not present:
                continue
            target = root / filename
            if client.startswith('codex') and (root / 'AGENTS.override.md').exists():
                target = root / 'AGENTS.override.md'
            if not (target.is_relative_to(h) or target.is_relative_to(paths.xdg_config_home())):
                raise ValueError('Home global fora do usuário; preservado')
            result[str(target)] = client
            # Prior effective file remains restorable after an override appears.
            if not discover and client.startswith('codex'):
                result[str(root / 'AGENTS.md')] = client
                result[str(root / 'AGENTS.override.md')] = client
        if len(result) > MAX_TARGETS:
            raise ValueError('Mais de 64 arquivos de orientação; lote recusado')
        return result

    def preference(self):
        row = read_object(self.config)
        if row is None:
            return False  # This host is explicitly enabled at installation.
        if set(row) != {'schema', 'enabled'} or type(row['enabled']) is not bool:
            raise ValueError('Preferência de orientação desconhecida; preservada')
        return row['enabled']

    def _save(self, row):
        if len(json.dumps(row).encode()) > MAX_RECEIPT:
            raise ValueError('Recibo de orientação excede 2 MiB; lote preservado')
        private_path(self.state, create=True)
        save_object(self.state, row)

    def _receipt(self):
        private_path(self.state)
        try:
            info = self.state.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Recibo de orientação não é privado')
        row = json.loads(bounded_read(self.state, MAX_RECEIPT))
        if (type(row.get('schema')) is not int or row['schema'] != 1
                or row.get('phase') not in ('intended', 'applied', 'restored')
                or type(row.get('enabled')) is not bool
                or str(uuid.UUID(row['operation_id'])) != row['operation_id']
                or not isinstance(row.get('entries'), list) or len(row['entries']) > MAX_TARGETS
                or not isinstance(row.get('changes'), list) or len(row['changes']) > MAX_TARGETS):
            raise ValueError('Recibo de orientação desconhecido; não repetir')
        allowed, seen = self._catalog(discover=False), set()
        for entry in row['entries']:
            if entry['path'] not in allowed or entry['path'] in seen:
                raise ValueError('Alvo do recibo fora do catálogo; preservado')
            seen.add(entry['path'])
            self._validate_snapshot(entry['before'])
            if entry['client'] != allowed[entry['path']]:
                raise ValueError('Cliente do recibo divergente')
            if 'legacy' in entry:
                self._validate_legacy(entry)
        changed = set()
        for change in row['changes']:
            if change['path'] not in seen or change['path'] in changed:
                raise ValueError('Efeito do recibo fora do catálogo')
            changed.add(change['path'])
            for key in ('before', 'after'):
                self._validate_snapshot(change[key])
            entry = next(e for e in row['entries'] if e['path'] == change['path'])
            expected = self._added(entry) if row['enabled'] else self._removed(entry, change['before'])
            if expected != change['after']:
                raise ValueError('Efeito não corresponde à orientação identificada')
        return row

    @staticmethod
    def _validate_snapshot(value):
        if value == {'kind': 'absent'}:
            return
        if (value.get('kind') != 'file' or type(value.get('mode')) is not int
                or value['mode'] & ~0o777 or value['mode'] & 0o022 or len(_bytes(value)) > 65536):
            raise ValueError('Original de orientação inválido')

    @staticmethod
    def _validate_legacy(entry):
        AgentGuidelines._validate_snapshot(entry['legacy'])
        raw = _bytes(entry['legacy'])
        a, b = raw.find(LEGACY_BEGIN), raw.find(LEGACY_END)
        if raw.count(LEGACY_BEGIN) != 1 or raw.count(LEGACY_END) != 1 or a >= b:
            raise ValueError('Bloco manual ambíguo')
        block = raw[a:b + len(LEGACY_END)]
        before = entry['before']
        original = _bytes(before) if before['kind'] == 'file' else HEADERS.get(entry['client'], b'')
        separator = b'\n\n' if original and not original.endswith(b'\n\n') else b''
        if _hash(block) != LEGACY_SHA or raw != original + separator + block + b'\n':
            raise ValueError('Migração alteraria diretrizes fora do bloco; preservada')

    @staticmethod
    def _added(entry):
        before = entry['before']
        data = _bytes(before) if before['kind'] == 'file' else HEADERS.get(entry['client'], b'')
        data += b'' if not data or data.endswith(b'\n\n') else b'\n\n'
        return _file(data + BLOCK, before.get('mode', 0o600))

    @staticmethod
    def _removed(entry, current):
        if current['kind'] == 'absent':
            return current
        data = _bytes(current)
        if current == entry.get('legacy'):
            return entry['before']
        added = AgentGuidelines._added(entry)
        if current == added:
            return entry['before']
        if BEGIN not in data and END not in data:
            if LEGACY_BEGIN in data or LEGACY_END in data:
                raise ValueError('Bloco manual divergente durante recuperação; preservado')
            return current  # Already removed externally: preserve that edit.
        if data.count(BEGIN) != 1 or data.count(END) != 1 or data.count(BLOCK) != 1:
            raise ValueError('Bloco do Fôlego editado ou ambíguo; preservado')
        before = entry['before']
        original = _bytes(before) if before['kind'] == 'file' else b''
        fragment = _bytes(added)[len(original):]
        # Remove the complete insertion when intact; otherwise only our marked body.
        remove = fragment if data.count(fragment) == 1 else BLOCK
        return _file(data.replace(remove, b'', 1), current['mode'])

    def _legacy(self, manifest, catalog):
        if manifest is None:
            return {}
        manifest = Path(manifest)
        private_path(manifest)
        snap = _snapshot(manifest)
        if snap.get('mode', 0) & 0o077:
            raise ValueError('Manifesto anterior não é privado')
        rows = json.loads(_bytes(snap)).get('files')
        if not isinstance(rows, list) or len(rows) > MAX_TARGETS:
            raise ValueError('Manifesto anterior desconhecido')
        result = {}
        for row in rows:
            name = row['path']
            if name not in catalog:
                continue  # Project instructions are never managed by this feature.
            leaf = row['backup']
            if Path(leaf).name != leaf or leaf in ('.', '..') or name in result:
                raise ValueError('Backup anterior ambíguo')
            original = _bytes(_snapshot(manifest.parent / leaf))
            current = _snapshot(Path(name))
            raw = _bytes(current)
            a, b = raw.find(LEGACY_BEGIN), raw.find(LEGACY_END)
            if (raw.count(LEGACY_BEGIN) != 1 or raw.count(LEGACY_END) != 1 or a >= b
                    or _hash(raw[a:b + len(LEGACY_END)]) != LEGACY_SHA
                    or _hash(original) != row['before_sha256']
                    or _hash(raw) != row['after_sha256']
                    or type(row['existed']) is not bool
                    or int(row['mode'], 8) != current['mode']):
                raise ValueError('Migração sem correspondência de bytes e hashes; preservada')
            before = _file(original, current['mode']) if row['existed'] else {'kind': 'absent'}
            entry = {'before': before, 'client': catalog[name], 'legacy': current}
            self._validate_legacy(entry)
            result[name] = (before, current)
        if not result:
            raise ValueError('Nenhum bloco manual comprovado neste catálogo')
        return result

    def status(self):
        enabled, row = self.preference(), self._receipt()
        catalog = self._catalog()
        conflicts = []
        entries = row['entries'] if row and row['phase'] != 'restored' else []
        for entry in entries:
            try:
                snap = _snapshot(Path(entry['path']))
                data = _bytes(snap) if snap['kind'] == 'file' else b''
                if data.count(BLOCK) != 1 or data.count(BEGIN) != 1 or data.count(END) != 1:
                    conflicts.append(entry['path'])
            except (OSError, ValueError):
                conflicts.append(entry['path'])
        pending = bool(row and row['phase'] == 'intended')
        managed = {e['path'] for e in entries}
        return {'schema': 1, 'enabled': enabled, 'default_enabled': False,
                'ok': not conflicts and not pending, 'operation_id': row['operation_id'] if row else None,
                'state': 'pending' if pending else 'conflict' if conflicts else row['phase'] if row else 'unconfigured',
                'managed': len(entries), 'discovered': len(catalog),
                'new_targets': [p for p in catalog if p not in managed],
                'conflicts': conflicts, 'scope': SCOPE,
                'message': ('Resultado pendente; verifique a operação antes de repetir.' if pending else
                            'Orientação alterada externamente; diretrizes preservadas.' if conflicts else
                            f'Orientação em {len(entries)} arquivos; procura automática ligada.' if enabled else
                            'Procura automática desligada; orientação do Fôlego removida.' if row else
                            'Procura automática desligada.')}

    def _write(self, path, expected, desired):
        private_path(path, create=True)
        if _snapshot(path) != expected:
            raise ValueError('Diretrizes mudaram antes da escrita; preservadas')
        if desired['kind'] == 'absent':
            path.unlink()
            fsync_dir(path.parent)
        else:
            write_atomic(path, _bytes(desired), mode=desired['mode'])
        if _snapshot(path) != desired:
            raise ValueError('Gravação da orientação não confirmada')

    def configure(self, enabled=None, *, reconcile=False, adopt=None):
        with Coordinator().lock(wait=.2):
            preference = self.preference()  # Unknown schema protects explicit enable too.
            if enabled is False:
                # Opt-out remains durable even if a receipt cannot be restored.
                save_object(self.config, {'schema': 1, 'enabled': False})
            row = self._receipt()
            if reconcile:
                if row and row['phase'] == 'intended':
                    if not all(_snapshot(Path(c['path'])) == c['after'] for c in row['changes']):
                        return {**self.status(), 'outcome': 'desconhecido'}
                    row['phase'] = 'applied' if row['enabled'] else 'restored'
                    self._save(row)
                    save_object(self.config, {'schema': 1, 'enabled': row['enabled']})
                return {**self.status(), 'outcome': 'sucesso'}
            chosen = preference if enabled is None else enabled
            if type(chosen) is not bool:
                raise ValueError('Preferência de orientação precisa ser booleana')
            if enabled is None and not chosen:
                return {**self.status(), 'outcome': 'sucesso'}
            if row and row['phase'] == 'intended' and chosen:
                return {**self.status(), 'outcome': 'desconhecido'}
            catalog = self._catalog()
            legacy = self._legacy(adopt, catalog) if adopt else {}
            entries = list(row['entries']) if row and row['phase'] != 'restored' else []
            changes = []
            if chosen:
                for entry in entries:
                    snap = _snapshot(Path(entry['path']))
                    raw = _bytes(snap) if snap['kind'] == 'file' else b''
                    if raw.count(BLOCK) != 1 or raw.count(BEGIN) != 1 or raw.count(END) != 1:
                        raise ValueError('Orientação gerenciada mudou; consulta necessária')
                known = {e['path'] for e in entries}
                for name, client in catalog.items():
                    if name in known:
                        continue
                    current = _snapshot(Path(name))
                    raw = _bytes(current) if current['kind'] == 'file' else b''
                    raw.decode('utf-8')  # Unknown text encodings remain protected.
                    if BEGIN in raw or END in raw or LEGACY_BEGIN in raw or LEGACY_END in raw:
                        if name not in legacy:
                            raise ValueError('Orientação preexistente sem recibo; preservada')
                    entry = {'path': name, 'client': client,
                             'before': legacy[name][0] if name in legacy else current}
                    if name in legacy:
                        entry['legacy'] = legacy[name][1]
                    desired = self._added(entry)
                    if len(_bytes(desired)) > 65536:
                        raise ValueError('Diretrizes excedem orçamento de 64 KiB')
                    entries.append(entry)
                    changes.append({'path': name, 'before': current, 'after': desired})
            else:
                for entry in entries:
                    current = _snapshot(Path(entry['path']))
                    desired = self._removed(entry, current)
                    if current != desired:
                        changes.append({'path': entry['path'], 'before': current, 'after': desired})
            if not changes and row and row['phase'] != 'intended' and row['enabled'] == chosen:
                return {**self.status(), 'outcome': 'sucesso'}
            intent = {'schema': 1, 'operation_id': str(uuid.uuid4()),
                      'parent_id': row['operation_id'] if row else None,
                      'enabled': chosen, 'phase': 'intended', 'entries': entries, 'changes': changes}
            self._save(intent)  # Intent and original bytes precede every effect.
            save_object(self.config, {'schema': 1, 'enabled': chosen})
            try:
                for change in changes:
                    self._write(Path(change['path']), change['before'], change['after'])
                intent['phase'] = 'applied' if chosen else 'restored'
                self._save(intent)
            except (OSError, ValueError) as exc:
                return {'ok': False, 'state': 'pending', 'enabled': chosen,
                        'operation_id': intent['operation_id'], 'outcome': 'desconhecido',
                        'message': str(exc) + '; consultar antes de repetir.', 'scope': SCOPE}
            return {**self.status(), 'outcome': 'sucesso'}
