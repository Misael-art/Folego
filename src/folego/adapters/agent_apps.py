"""Open the provider's local desktop/terminal window, with focus confirmation.

Never send a command to an agent or restart it. Existing CLI windows are found
by live process ancestry, not by titles resembling a provider name.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from ..core.agent_deliveries import identity, running_agents
from ..core.ai_sessions import NAMES
from ..core.ai_accounts import inventory, process_account, ROOT_KEYS

CLASSES = {
    'codex': r'^(codex-desktop|Codex)$',
    'web': r'^(codex-web-gpt-launcher)$',
    'claude': r'^(claude-desktop|Claude)$',
    'grok': r'^(grok|grok-desktop)$',
}
LAUNCHERS = {'codex': 'codex-desktop', 'web': 'codex-web-gpt-launcher',
             'claude': 'claude-desktop', 'grok': 'grok'}
TERMINALS = r'^(org\.kde\.konsole|konsole|org\.gnome\.Terminal|gnome-terminal-server|org\.communitybig\.ashyterm|kitty|Alacritty|foot|xfce4-terminal|xterm|org\.wezfurlong\.wezterm)$'


class AgentApps:
    def __init__(self, monitor, *, env=None, run=subprocess.run, discover=running_agents):
        self.monitor = monitor
        self.env = dict(os.environ if env is None else env)
        self.run, self.discover = run, discover
        self.wayland = self.env.get('XDG_SESSION_TYPE') == 'wayland'

    def _call(self, args, *, search=False):
        result = self.run(args, capture_output=True, text=True, timeout=4, env=self.env)
        if result.returncode and not (search and result.returncode == 1):
            raise RuntimeError('O desktop não confirmou a abertura da aplicação; avisos preservados')
        return result.stdout.strip()

    def _window_account(self, binary, window, account):
        text = self._call([binary, 'getwindowpid', window])
        if not text.isdigit() or identity(int(text)) is None: return False
        try:
            with Path('/proc', text, 'environ').open('rb') as stream:
                raw = stream.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024: return False
            key = ROOT_KEYS[account['provider']].encode() + b'='
            root = next((v[len(key):].decode() for v in raw.split(b'\0') if v.startswith(key)), None)
            if root is None:
                native_home = next((v[5:].decode() for v in raw.split(b'\0') if v.startswith(b'HOME=')), None)
                if not native_home or not Path(native_home).is_absolute(): return False
                home = Path(native_home)
                root = str(home / ('.codex' if account['provider'] == 'codex' else '.' + account['provider']))
                if account['provider'] == 'web': return False
            return str(Path(root).resolve()) == account['path']
        except (OSError, ValueError):
            return False

    def _windows(self, binary, provider, account=None):
        ids = self._call([binary, 'search', '--class', CLASSES[provider]], search=True).splitlines()
        pattern = r'\{[0-9a-fA-F-]{36}\}' if self.wayland else r'[0-9]+'
        existing = list(dict.fromkeys(i for i in ids if re.fullmatch(pattern, i)))[:16]
        if account is not None:
            existing = [w for w in existing if self._window_account(binary, w, account)]
        if existing: return existing
        ids = []
        # CLI processes: their terminal's owner must be in their live ancestry.
        for process in self.discover():
            if process['provider'] != ('codex' if provider == 'web' else provider) or process['server']:
                continue
            if identity(process['pid']) != process['identity']: continue
            if account is not None:
                actual_provider, actual_path = process_account(process, self.env)
                if actual_provider != provider or actual_path != account['path']: continue
            if provider in ('codex', 'web'):
                home = process['roots'].get('CODEX_HOME', '')
                config = Path(home) / 'config.toml'
                web = False
                try:
                    import tomllib
                    with config.open('rb') as stream: data = tomllib.loads(stream.read(65536).decode())
                    web = str(data.get('model', '')).startswith('chatgpt-web/')
                except (OSError, ValueError): pass
                if web != (provider == 'web'): continue
            parent = process['pid']
            for _ in range(24):
                current = identity(parent)
                if not current or current[1] <= 1: break
                parent = current[1]
                args = [binary, 'search', '--all', '--pid', str(parent), '--class', TERMINALS]
                ids.extend(self._call(args, search=True).splitlines())
        return list(dict.fromkeys(i for i in ids if re.fullmatch(pattern, i)))[:16]

    def _activate(self, binary, window):
        pid_text = self._call([binary, 'getwindowpid', window])
        if not pid_text.isdigit(): raise RuntimeError('Proprietário da janela desconhecido; avisos preservados')
        pid = int(pid_text)
        before = identity(pid)
        if before is None: raise RuntimeError('Janela não tem proprietário local confirmado')
        if self._call([binary, 'getwindowpid', window]) != pid_text or identity(pid) != before:
            raise RuntimeError('A janela mudou; avisos preservados')
        self._call([binary, 'windowactivate', window])
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self._call([binary, 'getactivewindow']) == window and identity(pid) == before:
                return
            time.sleep(.05)
        raise RuntimeError('A aplicação não recebeu foco; avisos preservados')

    def perform(self, action, value):
        if action == 'agent-billing':
            from ..core.ai_sessions import set_billing_day
            return set_billing_day(*value, env=self.env)
        if action == 'agent-reset-note':
            from ..core.ai_sessions import set_reset_note
            return set_reset_note(*value, env=self.env)
        provider, pending, *selected = value
        if action != 'agent-open' or provider not in CLASSES:
            raise ValueError('Aplicação desconhecida')
        binary = shutil.which('kdotool' if self.wayland else 'xdotool')
        if not binary: raise RuntimeError('Abertura indisponível: controle de janelas do desktop ausente')
        account = None
        if selected and selected[0]:
            account = next((a for a in inventory(self.env, discover=self.discover)
                            if a['provider'] == provider and a['account_id'] == selected[0]), None)
            if account is None: raise RuntimeError('Conta não identificada; avisos preservados')
            pending = [p for p in pending if p.get('account_id') == account['account_id']]
        windows = self._windows(binary, provider, account)
        if not windows:
            if account is not None:
                home = Path(self.env.get('HOME') or Path.home())
                canonical = str((home / ('.codex' if provider == 'codex' else '.' + provider)).resolve())
                if not account['default'] or provider == 'web' or account['path'] != canonical:
                    raise RuntimeError('Nenhuma janela desta conta identificada; abra o perfil no cliente. Avisos preservados')
            launcher = LAUNCHERS[provider]
            home = Path(self.env.get('HOME') or Path.home())
            data = Path(self.env.get('XDG_DATA_HOME') or home / '.local/share')
            files = [data / 'applications' / (launcher + '.desktop'),
                     Path('/usr/share/applications') / (launcher + '.desktop')]
            launch = shutil.which('gtk-launch')
            if not launch or not any(f.is_file() for f in files):
                raise RuntimeError('Nenhuma janela/atalho local identificado para ' + NAMES[provider] + '; avisos preservados')
            self._call([launch, launcher])
            # Observe the single launch; never repeat it after a timeout.
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                windows = self._windows(binary, provider, account)
                if windows: break
                time.sleep(.2)
            if not windows:
                raise RuntimeError('Abertura solicitada; janela ainda não confirmada. Avisos preservados')
        self._activate(binary, windows[-1])
        self.monitor.acknowledge(pending)
        return NAMES[provider] + ' aberto; avisos exibidos marcados como vistos'

    def close(self):
        pass  # user applications are deliberately independent of Fôlego's lifetime
