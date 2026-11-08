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


def optional_roster(data):
    """Optional names/roots only. Invalid content never blocks native sources."""
    from .ai_sessions import read_json
    roster = data / 'phasezero/ai-accounts/codex-profiles/profiles.json'
    if not roster.exists():
        return None, [], set()
    value = read_json(roster)
    profiles = value.get('profiles')
    current = value.get('current', {})
    current_label = current.get('label', 'Principal') if isinstance(current, dict) else None
    if (value.get('schemaVersion') != 1 or not isinstance(profiles, list) or len(profiles) > 16
            or not valid_label(current_label)):
        raise ValueError('Registro opcional de contas desconhecido')
    rows, archived, seen = [], set(), set()
    for profile in profiles:
        if (not isinstance(profile, dict) or not re.fullmatch(r'pz-[0-9a-f]{12}', str(profile.get('id', '')))
                or not valid_label(profile.get('label')) or type(profile.get('archived', False)) is not bool
                or profile['id'] in seen):
            raise ValueError('Registro opcional de contas inválido')
        seen.add(profile['id'])
        base = data / 'phasezero/codex' / profile['id']
        if profile.get('archived'):
            archived.update(str((base / suffix).resolve()) for suffix in ('native', 'web/codex-home'))
            continue
        for provider, suffix in (('codex', 'native'), ('web', 'web/codex-home')):
            path = base / suffix
            if any(p.is_symlink() for p in (base, path, path.parent)):
                raise ValueError('Perfil opcional redirecionado')
            rows.append(dict(provider=provider, path=str(path), label=profile['label']))
    return current_label, rows, archived


def valid_label(label):
    return isinstance(label, str) and bool(label.strip()) and len(label) <= 80 and all(ord(c) >= 32 for c in label)


def inventory(env=None, *, discover=None, discover_web=None):
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
    # The distributor's standalone default is ~/.codex-chatgpt-web. Its
    # launcher data normally lives in the application configuration directory.
    standalone_core = home / '.codex-chatgpt-web'
    if standalone_core.is_dir():
        rows.append(dict(provider='web', path=str(standalone_core), label='Web local',
                         web_core_home=str(standalone_core),
                         web_launcher_data=str(Path(env.get('XDG_CONFIG_HOME') or home / '.config') / 'Codex Web GPT')))
    archived_paths = set()
    try:
        primary_label, roster_rows, archived_paths = optional_roster(data)
    except (OSError, ValueError, TypeError):
        primary_label, roster_rows, archived_paths = None, [], set()
        roster_warning = 'Registro complementar de contas inválido; perfis não adotados'
    else:
        roster_warning = None
    if primary_label is not None:
        rows[0]['label'] = primary_label
        standalone_web = dict(rows[1], label='Web local')
        rows[1].update(path=str(data / 'phasezero/chatgpt-web/codex-home'), label=primary_label)
        if Path(standalone_web['path']).is_dir(): rows.append(standalone_web)
        rows.extend(roster_rows)
    for provider, key in ROOT_KEYS.items():
        if provider != 'web' and env.get(key):
            rows.append(dict(provider=provider, path=env[key], label='Ambiente'))
    if discover_web is None:
        from .web_gpt import installed_launchers
        discover_web = installed_launchers if native else lambda _env: []
    active_web = None
    for launcher in discover_web(env):
        if not isinstance(launcher, dict):
            continue
        path = launcher.get('codex_home')
        core = launcher.get('core_home')
        user_data = launcher.get('launcher_data')
        if (all(isinstance(value, str) and Path(value).is_absolute()
                and Path(value).resolve().is_relative_to(home) for value in (path, core, user_data))):
            active_web = str(Path(path).resolve())
            rows.append(dict(provider='web', path=active_web, label='Web instalado',
                             web_core_home=str(Path(core).resolve()),
                             web_launcher_data=str(Path(user_data).resolve())))
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
        for field in ('web_core_home', 'web_launcher_data'):
            if field in row and (row['provider'] != 'web' or not isinstance(row[field], str)
                                 or not Path(row[field]).is_absolute()):
                raise ValueError('Caminho do WebGPT inválido')
        label = row.get('label')
        if 'label' in row and not valid_label(label):
            raise ValueError('Identificação de conta inválida')
        path = str(Path(row['path']).resolve())
        key = (row['provider'], path)
        previous = unique.get(key, {})
        unique[key] = dict(previous, **row)
        unique[key].update(path=path, account_id=account_id(*key))
        if roster_warning:
            unique[key]['inventory_warning'] = roster_warning
    if len(unique) > 32:
        raise ValueError('Contas acima do orçamento')
    accounts = list(unique.values())
    for provider in PROVIDERS:
        group = [a for a in accounts if a['provider'] == provider]
        defaults = [a for a in group if a.get('default')]
        if len(defaults) > 1: raise ValueError('Mais de uma conta padrão para o provedor')
        primary = defaults[0] if defaults else (next((a for a in group if a['path'] == active_web), None)
                                                if provider == 'web' and active_web else None)
        primary = primary or next((a for a in group if Path(a['path']).is_dir()), group[0])
        for index, account in enumerate(group):
            account['default'] = account is primary
            account.setdefault('label', 'Conta ' + str(index + 1))
    return accounts
