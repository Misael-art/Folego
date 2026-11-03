"""Private custom clipboard texts and explicitly invoked keyboard macros."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from ..safely.atomicfile import write_atomic

MAX_FILE = 512 * 1024
MAX_ITEMS = 32
MODIFIERS = {'ctrl': 29, 'alt': 56, 'shift': 42, 'meta': 125}
KEYS = dict(esc=1, tab=15, space=57, backspace=14, enter=28, insert=110,
            delete=111, home=102, end=107, left=105, right=106, up=103,
            down=108, pgup=104, pgdown=109)
for chars, codes in (('1234567890', range(2, 12)), ('qwertyuiop', range(16, 26)),
                     ('asdfghjkl', range(30, 39)), ('zxcvbnm', range(44, 51))):
    KEYS.update(zip(chars, codes))
KEYS.update({f'f{i}': code for i, code in enumerate([*range(59, 69), 87, 88], 1)})
DEFAULTS = [dict(id='example-text', kind='text', title='123', text='123'),
            dict(id='example-desktop', kind='macro', title='Mostrar área de trabalho', action='desktop')]

# Shipped actions are independent of the private, user-edited library. Updating
# the application must neither append to that file nor resurrect deleted items.
STANDARD_SHORTCUTS = (
    ('Janelas', (
        ('switch-window', 'Alternar aplicativo', 'Alt+Tab'),
        ('overview', 'Visão geral das janelas', 'Meta+W'),
        ('tile-left', 'Janela à esquerda', 'Meta+Left'),
        ('tile-right', 'Janela à direita', 'Meta+Right'),
    )),
    ('Edição', (
        ('undo', 'Desfazer', 'Ctrl+Z'),
        ('redo', 'Refazer', 'Ctrl+Shift+Z'),
        ('save', 'Salvar', 'Ctrl+S'),
        ('find', 'Buscar no aplicativo', 'Ctrl+F'),
    )),
    ('Terminal', (
        ('terminal-copy', 'Copiar no terminal', 'Ctrl+Shift+C'),
        ('terminal-paste', 'Colar no terminal', 'Ctrl+Shift+V'),
    )),
)


def standard_shortcut(key):
    for _, items in STANDARD_SHORTCUTS:
        for identity, _, shortcut in items:
            if key == identity: return shortcut
    raise ValueError('Atalho padrão desconhecido; nenhuma tecla enviada')


def shortcut_codes(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError('Atalho inválido')
    parts = [p.strip().lower() for p in value.split('+')]
    if (not 1 <= len(parts) <= 5 or len(set(parts)) != len(parts)
            or any(p not in MODIFIERS for p in parts[:-1]) or parts[-1] not in KEYS):
        raise ValueError('Use um atalho como Ctrl+Alt+T, Meta+D ou Ctrl+Shift+F5')
    return [MODIFIERS[p] for p in parts[:-1]] + [KEYS[parts[-1]]]


def validate(entries):
    if not isinstance(entries, list) or len(entries) > MAX_ITEMS:
        raise ValueError('A biblioteca aceita até 32 itens')
    ids = set()
    for entry in entries:
        if not isinstance(entry, dict): raise ValueError('Item personalizado desconhecido')
        key, title, kind = entry.get('id'), entry.get('title'), entry.get('kind')
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,64}', key) or key in ids:
            raise ValueError('Identidade do item inválida ou repetida')
        ids.add(key)
        if (not isinstance(title, str) or not title.strip() or len(title) > 80
                or any(ord(c) < 32 for c in title)):
            raise ValueError('Informe um título de até 80 caracteres')
        if kind == 'text':
            text = entry.get('text')
            if (set(entry) != {'id', 'kind', 'title', 'text'} or not isinstance(text, str)
                    or not text or len(text) > 16000 or '\0' in text):
                raise ValueError('Informe um texto de até 16000 caracteres')
        elif kind == 'macro':
            action = entry.get('action')
            if action == 'desktop' and set(entry) == {'id', 'kind', 'title', 'action'}: continue
            if action == 'keys' and set(entry) == {'id', 'kind', 'title', 'action', 'shortcut'}:
                shortcut_codes(entry['shortcut'])
            else:
                raise ValueError('Macro desconhecida; configuração preservada')
        else:
            raise ValueError('Tipo personalizado desconhecido')
    return copy.deepcopy(entries)


class CustomPrompts:
    def __init__(self, path=None, *, env=None):
        env = dict(os.environ if env is None else env)
        home = Path(env.get('HOME') or Path.home())
        root = Path(env.get('XDG_CONFIG_HOME') or home / '.config')
        self.path = Path(path) if path is not None else root / 'folego/custom-prompts.json'

    def read(self):
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise ValueError('Biblioteca simbólica; arquivo preservado')
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return dict(operation='custom-load', entries=copy.deepcopy(DEFAULTS), revision='missing')
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError('Biblioteca sem arquivo regular próprio; preservada')
            raw = stream.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE: raise ValueError('Biblioteca acima do limite; arquivo preservado')
        try: value = json.loads(raw)
        except ValueError: raise ValueError('Biblioteca ilegível; arquivo preservado') from None
        if (not isinstance(value, dict) or set(value) != {'schema', 'entries'}
                or type(value['schema']) is not int or value['schema'] != 1):
            raise ValueError('Versão da biblioteca desconhecida; arquivo preservado')
        return dict(operation='custom-load', entries=validate(value['entries']),
                    revision=hashlib.sha256(raw).hexdigest())

    def save(self, entries, revision):
        entries = validate(entries)
        raw = (json.dumps(dict(schema=1, entries=entries), ensure_ascii=False, indent=2) + '\n').encode()
        if len(raw) > MAX_FILE: raise ValueError('Biblioteca acima do limite; reduza os textos')
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise ValueError('Biblioteca simbólica; arquivo preservado')
        lock = self.path.with_suffix('.lock')
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError('Lock da biblioteca desconhecido; preservado')
            fcntl.flock(fd, fcntl.LOCK_EX)
            if self.read()['revision'] != revision:
                raise ValueError('Biblioteca alterada em outra janela; atualize antes de salvar')
            write_atomic(self.path, raw, mode=0o600)
            result = self.read()
            result.update(operation='custom-save', message='Personalizações salvas')
            return result
        finally:
            os.close(fd)

    def resolve(self, key, revision):
        snapshot = self.read()
        if snapshot['revision'] != revision:
            raise ValueError('Item alterado; reabra o menu Custom antes de usar')
        entry = next((i for i in snapshot['entries'] if i['id'] == key), None)
        if entry is None: raise ValueError('Item removido; reabra o menu Custom')
        return entry
