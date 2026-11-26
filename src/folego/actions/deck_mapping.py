"""User-selected desktop mapping. Steam is passive. Only our transient mapper can be released."""
import os
from pathlib import Path
import sys
import subprocess
import time
import uuid

from ..adapters.accessibility import bounded_command
from .accessibility import Store, fresh, lease_blockers, read_object, save_object
from ..orchestration import Coordinator

PROFILES = {'steam': 'Steam Input', 'phasezero': 'PhaseZero'}
SERVICE = 'folego-accessibility.service'


def mapper_profile():
    if not os.access('/dev/uinput', os.W_OK):
        raise ValueError('A sessão precisa de acesso a /dev/uinput para o mapa PhaseZero.')


def native_enabled(report):
    roles = report.get('deck_desktop', {}).get('roles', {})
    return (sorted(roles.values()) == ['keyboard', 'pointer']
            and {d['key'] for d in report.get('devices', []) if d.get('enabled') is True} >= set(roles))


def resident():
    return Path('/proc/self/cgroup').read_text().strip().endswith('/' + SERVICE)


def unit_name(token):
    return 'folego-deck-map-' + str(uuid.UUID(token)) + '.service'


class MapperUnit:
    def state(self, token):
        name = unit_name(token)
        r = bounded_command(['/usr/bin/systemctl', '--user', 'show', name,
                             '-p', 'Description', '-p', 'LoadState', '-p', 'Transient',
                             '-p', 'ActiveState', '-p', 'DropInPaths', '-p', 'MainPID'], timeout=2)
        fields = dict(row.split('=', 1) for row in r.stdout.splitlines())
        if fields.get('LoadState') == 'not-found' and fields.get('ActiveState') == 'inactive':
            return 0
        if (r.returncode or fields.get('Transient') != 'yes' or fields.get('DropInPaths') != ''
                or fields.get('Description') != 'Folego Deck ' + token):
            raise ValueError('Identidade da unidade do mapeador não comprovada.')
        if fields.get('ActiveState') == 'active' and int(fields['MainPID']) > 1:
            return int(fields['MainPID'])
        raise ValueError('Transição do mapeador em andamento ou resultado incerto.')

    def start(self, token, root):
        r = bounded_command(['/usr/bin/systemd-run', '--user', '--quiet', '--collect', '--service-type=notify',
                             '--unit=' + unit_name(token), '--description=Folego Deck ' + token,
                             '--property=BindsTo=' + SERVICE, '--property=After=' + SERVICE,
                             '--property=SendSIGKILL=no', '--property=TimeoutStartSec=8',
                             '--', sys.executable, '-m', 'folego.adapters.deck_mapper', token], timeout=10)
        if r.returncode:
            raise ValueError('A partida do mapeador requer verificação.')

    def stop(self, token):
        if not self.state(token):
            return
        r = bounded_command(['/usr/bin/systemctl', '--user', 'stop', unit_name(token)], timeout=5)
        if r.returncode:
            raise ValueError('A liberação do controle requer verificação.')


def registered_games(store=None):
    from ..core.deck_games import validate_alias
    value = read_object((store or Store()).root / 'deck-games.json')
    if value is None:
        return []
    names = value.get('programs')
    if not isinstance(names, list) or len(names) > 128 or any(validate_alias(n) != n for n in names):
        raise ValueError('Catálogo adicional ilegível. Controle preservado.')
    return names


class DeckMapping:
    def __init__(self, store=None, coordinator=None, unit=None):
        self.store = store or Store()
        self.coordinator = coordinator or Coordinator()
        self.unit = unit or MapperUnit()
        self.receipt = self.store.root / 'deck-mapping.json'
        self.ready = None
        self.active = False
        self.mapper_pid = 0

    def read(self):
        s = read_object(self.receipt)
        if s is None:
            return {'schema': 1, 'choice': 'steam', 'token': '', 'stage': 'idle', 'starts': []}
        if (s.get('choice') not in PROFILES or s.get('stage') not in ('idle', 'starting', 'running', 'stopping', 'failed')
                or not isinstance(s.get('starts'), list) or len(s['starts']) > 12
                or any(type(ts) not in (int, float) or not 0 < ts < float('inf') for ts in s['starts'])
                or not isinstance(s.get('token'), str)
                or bool(s['token']) != (s['stage'] != 'idle')):
            raise ValueError('Recibo de controle inválido. Verifique o estado da sessão.')
        if s['token']:
            unit_name(s['token'])
            if not isinstance(s.get('boot'), str):
                raise ValueError('Identidade do boot do mapeador ausente.')
            uuid.UUID(s['boot'])
        return s

    def select(self, choice):
        if choice not in PROFILES:
            raise ValueError('Perfil de controle desconhecido.')
        with self.coordinator.lock(wait=.5):
            s = self.read()
            if s['stage'] == 'failed' and not self.unit.state(s['token']):
                s.update(stage='idle', token='')
            s['choice'] = choice
            save_object(self.receipt, s)
        return self.status()

    def pointer_token(self):
        s = self.read()
        if s['stage'] == 'idle':
            return None
        pid = self.unit.state(s['token'])
        if s['stage'] == 'running' and pid:
            return s['token']
        if s['stage'] == 'failed' and not pid:
            return None
        raise ValueError('O mapeador está em transição. Repita o teste após a estabilização.')

    def status(self):
        from .accessibility import _alive
        s = self.read()
        watched = read_object(self.store.root / 'watch-status.json') or {}
        row = watched.get('result', {}).get('mapping', {})
        if (row.get('choice') == s['choice'] and 0 <= time.time() - watched.get('checked_at', 0) <= 30
                and _alive(watched.get('owner')) is True):
            return row
        message = 'Preferência salva. Aguardando observação do monitor de entrada.'
        if s['choice'] == 'phasezero':
            try:
                mapper_profile()
            except (ValueError, OSError) as exc:
                message = str(exc)
        return {'choice': s['choice'], 'message': message}

    def catalog(self, add=None, remove=None):
        from ..core.deck_games import EMULATORS, FRONTENDS, validate_alias
        with self.coordinator.lock(wait=.5):
            names = set(registered_games(self.store))
            if add or remove:
                name = validate_alias(add or remove)
                if add:
                    names.add(name)
                else:
                    names.discard(name)
                if len(names) > 128:
                    raise ValueError('Limite de 128 entradas adicionais.')
                save_object(self.store.root / 'deck-games.json', {'schema': 1, 'programs': sorted(names)})
        return {'frontends': sorted(FRONTENDS), 'emulators': sorted(EMULATORS), 'additional': sorted(names)}

    def perform(self, action, value=None):
        if action == 'catalog':
            return self.catalog()
        if action == 'select':
            return self.select(value)
        return self.status()

    def close(self):
        pass

    @staticmethod
    def deferred_start(s):
        # Written by the child only when it yields before grabbing either input.
        return {'schema': 1, 'token': s['token'], 'boot': s['boot'], 'state': 'yielded-before-grab'}

    def _observe_unit(self, s):
        pid = self.unit.state(s['token'])
        if pid and s['stage'] == 'starting':
            s['stage'] = 'running'
            save_object(self.receipt, s)
        elif not pid and s['stage'] == 'stopping':
            s.update(stage='idle', token='')
            save_object(self.receipt, s)
        elif not pid and s['stage'] in ('starting', 'running'):
            if (s['stage'] == 'starting' and
                    read_object(self.store.root / 'deck-map-yield.json') == self.deferred_start(s)):
                s.update(stage='idle', token='')
                self.ready = None
            else:
                s['stage'] = 'failed'
            save_object(self.receipt, s)
        self.mapper_pid = pid
        return pid

    def _release(self, s, reason):
        self.ready = None
        if s['stage'] == 'stopping':
            return 'Aguardando confirmação da liberação do controle.'
        s['stage'] = 'stopping'
        save_object(self.receipt, s)
        self.unit.stop(s['token'])
        self.active = bool(self._observe_unit(s))
        return reason

    def _tick(self, s, report, guard):
        if s['token'] and report.get('boot_id') and s.get('boot') != report['boot_id']:
            if self.unit.state(s['token']):
                raise ValueError('Uma unidade inesperada possui a identidade de outro boot.')
            s.update(stage='idle', token='')
            save_object(self.receipt, s)
        pid = self._observe_unit(s) if s['token'] else 0
        self.active = bool(pid)
        if s['choice'] == 'steam':
            if pid:
                return self._release(s, 'Mapa PhaseZero liberado. Aguardando o controle do desktop.')
            self.ready = None
            for provider in report.get('providers', []):
                if provider.get('name') == 'EmuAtlas/RetroFE' and provider.get('state') == 'pending':
                    return 'EmuAtlas/RetroFE está com a sessão de controle ou a restauração pendente.'
            if report.get('deck_control_owner'):
                return report['deck_control_owner']
            native = report.get('deck_desktop', {}).get('native_available')
            steam = report.get('desktop_profiles', {}).get('touchpad', {})
            if steam.get('desktop_output') or steam.get('state') == 'healthy':
                return 'Steam Input em uso no desktop.'
            if native:
                return 'Interfaces de mouse e teclado presentes. Teste o movimento. Com o Steam fechado, PhaseZero fornece os atalhos.'
            return 'Steam Input selecionado. Mapeamento atual do controle sem confirmação.'
        if s['stage'] == 'failed':
            return 'O mapeador saiu ou a partida ficou incerta. Confira a sessão e reaplique a escolha.'
        if s['stage'] == 'stopping':
            return 'Aguardando liberação da unidade anterior.'
        if not pid:
            mapper_profile()
        layout = report.get('deck_desktop', {})
        if (not fresh(report) or report.get('backend') != 'kwin' or report.get('errors')
                or layout.get('display') not in ('portátil', 'monitor externo')):
            reason = 'Aguardando a sessão KDE e o controle interno do Deck.'
        elif not native_enabled(report):
            reason = 'Aguardando o teclado e o ponteiro internos habilitados no KWin.'
        else:
            blockers = report.get('blockers', []) or lease_blockers(self.store.root)
            reason = '; '.join(blockers) or guard.desktop_blocker(report, mapper_pid=pid)
        if reason:
            self.ready = None
            return self._release(s, reason) if pid else reason
        if pid:
            return 'Fôlego está aplicando o mapa PhaseZero no desktop.'
        if not layout.get('native_available'):
            self.ready = None
            return 'Aguardando a interface livre e o ponteiro nativo de retorno.'
        identity = report['boot_id'], report['service_owner'], layout['display']
        previous, self.ready = self.ready, (identity, report['mono'])
        if not previous or previous[0] != identity or not 0 < report['mono'] - previous[1] <= 30:
            return 'Verificando estabilidade do desktop antes de ativar PhaseZero.'
        starts = [ts for ts in s['starts'] if ts > time.time() - 3600]
        if len(starts) >= 12:
            return 'Limite de 12 ativações por hora atingido. Controle do jogo preservado.'
        if not resident():
            return 'Aguardando o monitor de entrada da sessão.'
        token = str(uuid.uuid4())
        latest = guard._native.collect()
        if (self.unit.state(token) or not native_enabled(latest) or not fresh(latest) or latest.get('errors') or latest.get('blockers')
                or latest.get('deck_desktop') != layout or latest.get('boot_id') != identity[0]
                or latest.get('service_owner') != identity[1] or guard.desktop_blocker(latest, mapper_pid=0)
                or lease_blockers(self.store.root)):
            self.ready = None
            return 'Contexto do controle mudou durante a verificação.'
        s.update(token=token, boot=report['boot_id'], kwin=report['service_owner'], stage='starting', starts=[*starts, time.time()])
        save_object(self.receipt, s)
        self.unit.start(token, self.store.root)
        self.active = bool(self._observe_unit(s))
        return 'Fôlego está aplicando o mapa PhaseZero.' if self.active else 'Partida sem confirmação.'

    def tick(self, report, guard):
        s = self.read()
        if s['choice'] == 'steam' and not s['token']:
            return {'choice': 'steam', 'message': self._tick(s, report, guard)}
        with self.coordinator.lock(wait=.5):
            s = self.read()
            try:
                message = self._tick(s, report, guard)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                self.ready = None
                message = str(exc)
            return {'choice': s['choice'], 'message': message}

    def yield_to_game(self, guard):
        """Between full samples only while this watcher has a running mapper."""
        with self.coordinator.lock(wait=.2):
            s = self.read()
            if not s['token']:
                self.ready = None
                self.active = False
                return
            if (s['choice'] == 'steam' or guard._game_blocker(mapper_pid=self.mapper_pid)
                    or lease_blockers(self.store.root)):
                self.release_for_lease_locked(s)

    def release_for_lease_locked(self, s):
        self.active = bool(s['token'] and self._observe_unit(s))
        if self.active:
            self._release(s, 'Controle liberado.')
        if self.active or s['stage'] in ('starting', 'stopping'):
            raise ValueError('Aguardando liberação confirmada do mapeador.')
