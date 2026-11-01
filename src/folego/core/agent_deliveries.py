"""New completed primary sessions, not tool calls or a lifetime message total.

Only native completion records are counted. The notification epoch and viewed
receipts belong to Fôlego; conversations, credentials and agent configs are never
written. A first activation starts watching new work, avoiding historical floods.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time
import tomllib

from .. import paths
from ..safely.atomicfile import write_atomic
from .ai_sessions import NAMES, read_json, timestamp
from .procfs import _parse_stat

MAX_SESSIONS = 128
MAX_TAIL = 64 * 1024


def identity(pid, proc=Path('/proc')):
    try:
        root = proc / str(pid)
        if root.stat().st_uid != os.getuid():
            return None
        parsed = _parse_stat((root / 'stat').read_text())
        return (parsed[0], parsed[2], parsed[7]) if parsed else None
    except (OSError, ValueError):
        return None


def running_agents(proc=Path('/proc')):
    """Read selected provider paths only; never export an environment or prompt."""
    result = []
    for directory in itertools.islice(proc.iterdir(), 8192):
        if not directory.name.isdigit():
            continue
        try:
            if directory.stat().st_uid != os.getuid():
                continue
            exe = Path(os.readlink(directory / 'exe'))
            provider = None
            if exe.name == 'codex': provider = 'codex'
            elif re.fullmatch(r'grok(?:-[0-9.]+-linux-(?:x86_64|aarch64))?', exe.name): provider = 'grok'
            elif exe.name == 'claude' or (exe.parent.name == 'versions' and exe.parent.parent.name == 'claude'):
                provider = 'claude'
            if provider is None and exe.name != 'node':
                continue
            with (directory / 'cmdline').open('rb') as stream:
                argv = stream.read(8192).split(b'\0')[:4]
            if provider is None:
                if any(b'@anthropic-ai/claude-code/' in a for a in argv): provider = 'claude'
                else: continue
            selected = {}
            with (directory / 'environ').open('rb') as stream:
                raw = stream.read(256 * 1024)
            for entry in raw.split(b'\0'):
                key, _, value = entry.partition(b'=')
                if key in (b'CODEX_HOME', b'CLAUDE_CONFIG_DIR', b'GROK_HOME'):
                    selected[key.decode()] = value.decode(errors='strict')
            pid = int(directory.name)
            result.append(dict(pid=pid, identity=identity(pid, proc), provider=provider,
                               server=any(b'app-server' in a for a in argv), roots=selected))
        except (OSError, ValueError, UnicodeError):
            continue
    return result


def account_roots(env):
    home = Path(env.get('HOME') or Path.home())
    config = Path(env.get('XDG_CONFIG_HOME') or home / '.config') / 'folego/ai-sessions.json'
    accounts = [dict(provider='codex', path=env.get('CODEX_HOME') or str(home / '.codex')),
                dict(provider='web', path=str(home / '.local/share/codex-web-gpt/codex-home'))]
    if config.exists():
        data = read_json(config)
        if data.get('schema') != 1 or not isinstance(data.get('accounts', []), list):
            raise ValueError('configuração de contas desconhecida')
        accounts.extend(data.get('accounts', []))
    accounts.extend([dict(provider='claude', path=env.get('CLAUDE_CONFIG_DIR') or str(home / '.claude')),
                     dict(provider='grok', path=env.get('GROK_HOME') or str(home / '.grok'))])
    for account in accounts:
        if (not isinstance(account, dict) or account.get('provider') not in NAMES
                or not isinstance(account.get('path'), str) or not Path(account['path']).is_absolute()):
            raise ValueError('conta ou caminho desconhecido')
    return accounts


def _children(directory, limit=256):
    with os.scandir(directory) as entries:
        result = list(itertools.islice(entries, limit + 1))
    if len(result) > limit:
        raise ValueError('inventário de sessões acima do orçamento')
    return result


def session_files(provider, root, since):
    if provider in ('codex', 'web'):
        databases = list(root.glob('state_*.sqlite'))
        if databases:
            if len(databases) != 1:
                raise ValueError('índice de sessões ambíguo')
            with sqlite3.connect(databases[0].as_uri() + '?mode=ro', uri=True, timeout=.2) as db:
                columns = {r[1] for r in db.execute('pragma table_info(threads)')}
                if not {'rollout_path', 'archived', 'source'} <= columns:
                    raise ValueError('schema de sessões desconhecido')
                # An indexed session last updated before notification activation
                # cannot contain a new delivery, even if an old rollout moved.
                updated = ', updated_at' if 'updated_at' in columns else ''
                rows = db.execute('select rollout_path, source' + updated + ' from threads where archived=0 limit ?',
                                  (MAX_SESSIONS + 1,)).fetchall()
            if len(rows) > MAX_SESSIONS:
                raise ValueError('sessões acima do orçamento')
            files = []
            for row in rows:
                p, source = row[:2]
                if str(source).startswith('{'): continue
                if updated and timestamp(row[2]) and row[2] < since - 2: continue
                files.append((Path(p), True))
            return files
        # Unlike quota sampling, a notification total must never silently sample
        # just the newest 40 files or discard older session directories.
        directories = [root / 'sessions']
        if not directories[0].is_dir(): return []
        for _ in range(3):
            following = []
            for directory in directories:
                following.extend(Path(e.path) for e in _children(directory)
                                 if e.is_dir(follow_symlinks=False))
            if len(following) > 128: raise ValueError('inventário de sessões acima do orçamento')
            directories = following
        files = []
        for directory in directories:
            files.extend(Path(e.path) for e in _children(directory)
                         if e.is_file(follow_symlinks=False) and e.name.startswith('rollout-')
                         and e.name.endswith('.jsonl') and e.stat().st_mtime >= since)
        if len(files) > MAX_SESSIONS: raise ValueError('sessões acima do orçamento')
        return [(p, False) for p in files]
    base = root / ('projects' if provider == 'claude' else 'sessions')
    candidates = []
    for project in _children(base):
        if not project.is_dir(follow_symlinks=False): continue
        for entry in _children(Path(project.path)):
            path = Path(entry.path)
            if provider == 'claude' and entry.is_file(follow_symlinks=False) and path.suffix == '.jsonl':
                candidates.append(path)
            elif provider == 'grok' and entry.is_dir(follow_symlinks=False):
                transcript = path / 'updates.jsonl'
                if transcript.is_file(): candidates.append(transcript)
    candidates = [p for p in candidates if p.stat().st_mtime >= since]
    if len(candidates) > MAX_SESSIONS:
        raise ValueError('sessões acima do orçamento')
    return [(p, False) for p in candidates]


def last_delivery(provider, path, since, now, primary=False):
    """Return the latest explicit final event of one primary conversation."""
    with path.open('rb') as stream:
        if provider in ('codex', 'web'):
            if primary:
                session = path.stem  # primary identity established by the native index
            else:
                meta = json.loads(stream.readline(MAX_TAIL))
                payload = meta.get('payload', {})
                if meta.get('type') != 'session_meta' or isinstance(payload.get('source'), dict):
                    return None
                session = payload.get('id') or payload.get('session_id')
        else:
            session = path.stem if provider == 'claude' else path.parent.name
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - MAX_TAIL))
        if size > MAX_TAIL: stream.readline()
        raw = stream.read(MAX_TAIL)
    if not raw.endswith(b'\n'):
        raise ValueError('observação de conclusão incompleta')
    pending = None
    observed = False
    for line in raw.splitlines():
        record = json.loads(line)
        if not isinstance(record, dict): raise ValueError('registro inválido')
        at = timestamp(record.get('timestamp'))
        if not at: continue
        if at > now + 5: raise ValueError('relógio da observação desconhecido')
        token = None
        if provider in ('codex', 'web'):
            event = record.get('payload') or {}
            if record.get('type') != 'event_msg': continue
            kind = event.get('type')
            if kind in ('task_started', 'user_message', 'turn_aborted'):
                observed = True
                pending = None
            elif kind == 'task_complete':
                observed = True
                token = event.get('turn_id')
                if not token: raise ValueError('conclusão sem identidade')
        elif provider == 'claude':
            if record.get('isSidechain'): continue
            if record.get('type') == 'api-request':
                observed = True
                pending = None
            message = record.get('message') or {}
            content = message.get('content', []) if isinstance(message, dict) else []
            if record.get('type') == 'user' and (isinstance(content, str) or
                    any(c.get('type') in ('text', 'image', 'document') for c in content if isinstance(c, dict))):
                pending = None
                observed = True
            elif (record.get('type') == 'assistant' and message.get('stop_reason') == 'end_turn'
                  and any(c.get('type') == 'text' for c in content if isinstance(c, dict))):
                token = record.get('uuid')
                observed = True
                if not token: raise ValueError('conclusão sem identidade')
        else:
            update = (record.get('params') or {}).get('update') or {}
            kind = update.get('sessionUpdate')
            if kind in ('user_message_chunk', 'turn_started'):
                observed = True
                pending = None
            elif kind == 'turn_completed':
                observed = True
                pending = None
                if update.get('stop_reason') == 'end_turn':
                    token = update.get('prompt_id')
                    if not token: raise ValueError('conclusão sem identidade')
        if token and session:
            pending = dict(at=at, event=str(token)) if at >= since else None
    if size > MAX_TAIL and not observed:
        raise ValueError('estado da sessão fora da cauda observável')
    return pending


class DeliveryMonitor:
    def __init__(self, *, env=None, state=None, clock=time.time, discover=running_agents):
        self.env = dict(os.environ if env is None else env)
        self.state = Path(state) if state else paths.state_dir() / 'ai-deliveries.json'
        self.clock, self.discover = clock, discover
        self.lock = threading.RLock()
        self.cache = {}
        self.roots = None
        self.roots_at = 0

    def _load(self):
        self.state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.state.is_symlink() or self.state.parent.is_symlink():
            raise ValueError('estado de avisos simbólico')
        if self.state.exists():
            value = read_json(self.state)
            if (value.get('schema') != 1 or not timestamp(value.get('since'))
                    or not isinstance(value['since'], (int, float)) or value['since'] > self.clock() + 5
                    or not isinstance(value.get('seen'), dict) or len(value['seen']) > 2048):
                raise ValueError('estado de avisos desconhecido')
            for session, receipt in value['seen'].items():
                if (not re.fullmatch('[0-9a-f]{64}', session) or not isinstance(receipt, dict)
                        or not isinstance(receipt.get('event'), str)
                        or not re.fullmatch('[0-9a-f]{64}', receipt['event'])
                        or not timestamp(receipt.get('at'))):
                    raise ValueError('recibo de entrega desconhecido')
            return value
        value = dict(schema=1, since=self.clock(), seen={})
        self._save(value)
        return value

    def _save(self, value):
        write_atomic(self.state, (json.dumps(value, sort_keys=True) + '\n').encode(), mode=0o600)

    def _accounts(self, now):
        if self.roots is not None and now - self.roots_at < 20: return self.roots
        accounts = account_roots(self.env)
        for process in self.discover():
            if process['provider'] in ('claude', 'grok'):
                key = 'CLAUDE_CONFIG_DIR' if process['provider'] == 'claude' else 'GROK_HOME'
                if process['roots'].get(key):
                    accounts.append(dict(provider=process['provider'], path=process['roots'][key]))
            root = process['roots'].get('CODEX_HOME')
            if process['provider'] == 'codex' and root:
                provider = 'codex'
                config = Path(root) / 'config.toml'
                try:
                    with config.open('rb') as stream: value = tomllib.loads(stream.read(MAX_TAIL).decode())
                    if str(value.get('model', '')).startswith('chatgpt-web/'):
                        provider = 'web'
                except (OSError, ValueError): pass
                accounts.append(dict(provider=provider, path=root))
        if len(accounts) > 64: raise ValueError('contas acima do orçamento')
        if any(not Path(a['path']).is_absolute() for a in accounts):
            raise ValueError('caminho nativo não absoluto')
        self.roots = list({(a['provider'], str(Path(a['path']).expanduser().resolve())) for a in accounts})
        self.roots_at = now
        return self.roots

    def collect(self):
        with self.lock:
            value = self._load()
            now = self.clock()
            rows = {p:dict(provider=p, pending=[], complete=True, available=False) for p in NAMES}
            visited = set()
            for provider, directory in self._accounts(now):
                if provider not in rows: raise ValueError('provedor desconhecido')
                root = Path(directory)
                if not root.is_dir(): continue
                row = rows[provider]
                try:
                    files = session_files(provider, root, value['since'])
                    row['available'] = True
                    for path, primary in files:
                        visited.add(str(path))
                        try:
                            receipt = self._receipt(provider, path, primary, value, now)
                            if receipt: row['pending'].append(receipt)
                        except (OSError, ValueError, TypeError):
                            row['complete'] = False
                except (OSError, ValueError, TypeError, sqlite3.Error):
                    row['complete'] = False
            for row in rows.values():
                # Verified completions remain useful when another session cannot
                # be inspected. The UI labels that positive count as a minimum.
                row['count'] = len(row['pending']) if row['pending'] or (row['available'] and row['complete']) else None
            self.cache = {p: cached for p, cached in self.cache.items() if p in visited}
            return list(rows.values())

    def _receipt(self, provider, path, primary, value, now):
        info = path.stat()
        if info.st_mtime < value['since']: return None
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            raise ValueError('transcrição não regular')
        stamp = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        cached = self.cache.get(str(path))
        if cached and cached[0] == stamp: pending = cached[1]
        else:
            pending = last_delivery(provider, path, value['since'], now, primary)
            self.cache[str(path)] = (stamp, pending)
        if not pending: return None
        session = hashlib.sha256((provider + '\0' + str(path.resolve())).encode()).hexdigest()
        event = hashlib.sha256((session + '\0' + pending['event']).encode()).hexdigest()
        seen = value['seen'].get(session, {})
        if seen and (seen.get('event') == event or seen.get('at', 0) > pending['at']): return None
        return dict(session=session, event=event, at=pending['at'])

    def acknowledge(self, pending):
        """Only the snapshot whose application was actually opened is viewed."""
        with self.lock:
            value = self._load()
            for item in pending:
                if (not re.fullmatch('[0-9a-f]{64}', item['session']) or
                        not re.fullmatch('[0-9a-f]{64}', item['event']) or not timestamp(item['at'])):
                    raise ValueError('recibo de entrega inválido')
                current = value['seen'].get(item['session'], {})
                if current.get('at', 0) > item['at']: continue
                value['seen'][item['session']] = dict(event=item['event'], at=item['at'])
            if len(value['seen']) > 2048: raise ValueError('recibos acima do orçamento')
            self._save(value)
