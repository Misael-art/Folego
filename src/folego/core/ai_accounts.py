"""Bounded, read-only native account inventory shared by quotas and deliveries.

Fôlego owns its configuration. An optional PhaseZero roster supplies labels and
native paths only; neither its code nor any running PhaseZero service is used.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tomllib

PROVIDERS = ('codex', 'web', 'claude', 'grok')
ROOT_KEYS = dict(codex='CODEX_HOME', web='CODEX_HOME', claude='CLAUDE_CONFIG_DIR', grok='GROK_HOME')


def account_id(provider, path):
    return hashlib.sha256((provider + '\0' + str(Path(path).resolve())).encode()).hexdigest()[:24]


def settings(env):
    from .ai_sessions import read_json
    home = Path(env.get('HOME') or Path.home())
    path = Path(env.get('XDG_CONFIG_HOME') or home / '.config') / 'folego/ai-sessions.json'
    value = read_json(path) if path.exists() else dict(schema=1)
    if value.get('schema') != 1:
        raise ValueError('Configuração de IAs desconhecida; arquivo preservado')
    return value


def process_account(process, env):
    provider = process['provider']
    home = Path(env.get('HOME') or Path.home())
    path = process['roots'].get(ROOT_KEYS[provider]) or str(home / ('.codex' if provider == 'codex' else '.' + provider))
    if provider == 'codex':
        try:
            with (Path(path) / 'config.toml').open('rb') as stream:
                value = tomllib.loads(stream.read(65536).decode())
            if str(value.get('model', '')).startswith('chatgpt-web/'):
                provider = 'web'
        except (OSError, ValueError):
            pass
    return provider, str(Path(path).resolve())


def inventory(env=None, *, discover=None):
    from .ai_sessions import read_json
    native = env is None
    env = dict(os.environ if native else env)
    home = Path(env.get('HOME') or Path.home()).resolve()
    data = Path(env.get('XDG_DATA_HOME') or home / '.local/share')
    configuration = settings(env)
    configured = configuration.get('accounts', [])
    if not isinstance(configured, list) or len(configured) > 16:
        raise ValueError('Inventário de contas inválido/acima do orçamento')
    rows = [dict(provider=p, path=str(home / ('.codex' if p == 'codex' else '.' + p)), label='Principal')
            for p in PROVIDERS if p != 'web']
    rows.insert(1, dict(provider='web', path=str(data / 'codex-web-gpt/codex-home'), label='Principal'))
    roster = data / 'phasezero/ai-accounts/codex-profiles/profiles.json'
    archived_paths = set()
    # Absence is supported; an unreadable/unknown roster is a visible inventory
    # failure, never permission to probe arbitrary directories or archived profiles.
    if roster.exists():
        value = read_json(roster)
        profiles = value.get('profiles')
        current = value.get('current', {})
        if (value.get('schemaVersion') != 1 or not isinstance(profiles, list) or len(profiles) > 16
                or not isinstance(current, dict) or not isinstance(current.get('label', 'Principal'), str)):
            raise ValueError('Registro opcional de contas desconhecido')
        rows[0]['label'] = current.get('label', 'Principal')
        standalone_web = dict(rows[1], label='Web local')
        rows[1].update(path=str(data / 'phasezero/chatgpt-web/codex-home'), label=rows[0]['label'])
        if Path(standalone_web['path']).is_dir(): rows.append(standalone_web)
        seen = set()
        for profile in profiles:
            if (not isinstance(profile, dict) or not re.fullmatch(r'pz-[0-9a-f]{12}', str(profile.get('id', '')))
                    or not isinstance(profile.get('label'), str) or type(profile.get('archived', False)) is not bool
                    or profile['id'] in seen):
                raise ValueError('Registro opcional de contas inválido')
            seen.add(profile['id'])
            base = data / 'phasezero/codex' / profile['id']
            if profile.get('archived'):
                archived_paths.update(str((base / suffix).resolve()) for suffix in ('native', 'web/codex-home'))
                continue
            for provider, suffix in (('codex', 'native'), ('web', 'web/codex-home')):
                path = base / suffix
                if any(p.is_symlink() for p in (base, path, path.parent)):
                    raise ValueError('Perfil opcional redirecionado; inventário não confirmado')
                rows.append(dict(provider=provider, path=str(path), label=profile['label']))
    for provider, key in ROOT_KEYS.items():
        if provider != 'web' and env.get(key):
            rows.append(dict(provider=provider, path=env[key], label='Ambiente'))
    if discover is None:
        from .agent_deliveries import running_agents
        discover = running_agents if native else lambda: []
    for process in discover():
        provider, path = process_account(process, env)
        if Path(path).is_relative_to(home) and path not in archived_paths:
            rows.append(dict(provider=provider, path=path))
    rows.extend(configured)  # explicit Fôlego labels/defaults take precedence
    unique = {}
    for row in rows:
        if (not isinstance(row, dict) or row.get('provider') not in PROVIDERS
                or not isinstance(row.get('path'), str) or not Path(row['path']).is_absolute()
                or type(row.get('default', False)) is not bool):
            raise ValueError('Configuração de conta inválida')
        label = row.get('label')
        if 'label' in row and (not isinstance(label, str) or not label.strip() or len(label) > 80
                                  or any(ord(c) < 32 for c in label)):
            raise ValueError('Identificação de conta inválida')
        path = str(Path(row['path']).resolve())
        key = (row['provider'], path)
        previous = unique.get(key, {})
        unique[key] = dict(previous, **row)
        unique[key].update(path=path, account_id=account_id(*key))
    if len(unique) > 32:
        raise ValueError('Contas acima do orçamento')
    accounts = list(unique.values())
    for provider in PROVIDERS:
        group = [a for a in accounts if a['provider'] == provider]
        defaults = [a for a in group if a.get('default')]
        if len(defaults) > 1: raise ValueError('Mais de uma conta padrão para o provedor')
        primary = defaults[0] if defaults else next((a for a in group if Path(a['path']).is_dir()), group[0])
        for index, account in enumerate(group):
            account['default'] = account is primary
            account.setdefault('label', 'Conta ' + str(index + 1))
    return accounts
