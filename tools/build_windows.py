"""Build the native Windows package from this checkout, without downloads.

Windows shares Linux health/battery policy via generated data, not a second
hand-maintained copy of its thresholds. No Linux runtime/config is deployed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from folego.core.policy import battery_band, HealthThresholds
from folego.core.development_prompts import PROMPTS, PROMPT_CATEGORIES, text as prompt_text
from folego.ui.palettes import THEMES, DEFAULT_THEME  # pure module: no Qt import

FILES = ('Folego.ps1', 'Folego.Core.ps1', 'Folego.Manage.ps1', 'Folego.Sequence.ps1', 'Folego.AI.ps1', 'Folego.View.ps1', 'Folego.Widget.ps1',
         'Folego.Prompts.ps1', 'Folego.PromptMenu.ps1', 'Collect.ps1', 'Native.cs', 'Widget.cs', 'TextContext.cs', 'Test-Folego.ps1', 'DeckBootstrap.ps1')
CAPABILITIES = ('monitor', 'power-plan-receipts', 'thermal-profiles', 'process-triage', 'startup-approval',
                'widget-views', 'color-themes', 'taskbar-indicators', 'logon-sequence', 'local-volume-inventory',
                'desktop-shortcuts', 'battery-runtime-estimate', 'boot-timeline', 'storage-hardware-events',
                'local-codex-quota', 'prompt-library', 'text-context-companion')
# Linux widget views (ui/desktop_preferences.py) plus the Windows-only taskbar indicators,
# which are the default opening view on Windows.
VIEWS = (('central', 'Central do Fôlego'), ('taskbar', 'Barra de tarefas'), ('mini', 'Mini horizontal'), ('compact', 'Widget compacto'),
         ('left', 'Lateral esquerda'), ('right', 'Lateral direita'), ('top', 'Barra superior'))


def appearance() -> dict:
    """Linux console themes with their already contrast-checked tokens; no second palette copy."""
    themes = {}
    for key, theme in THEMES.items():
        tokens = theme.tokens
        themes[key] = {
            'name': theme.name, 'description': theme.description,
            'tokens': {role: getattr(tokens, role) for role in (
                'background', 'surface', 'surface_alt', 'text', 'muted', 'accent', 'accent_text',
                'ok', 'warning', 'danger', 'focus', 'border')},
            'actions': list(tokens.actions),
        }
    # Windows applies opacity to the whole widget window, text included, so it is capped.
    return {'default_theme': DEFAULT_THEME, 'default_view': 'taskbar', 'views': [{'key': k, 'name': n} for k, n in VIEWS],
            'transparency_max': 60, 'transparency_steps': [0, 15, 30, 45, 60], 'themes': themes}

# Thermal guard: Windows triage rules for the ACPI zone, not a sensor-certified limit.
# Profiles only touch PROCTHROTTLEMAX/PERFBOOSTMODE of the active, existing scheme.
THERMAL = {
    'poll_seconds': 5, 'raise_average_c': 80, 'raise_samples': 3, 'spike_c': 90,
    'recover_c': 70, 'recover_samples': 60, 'max_switches_per_hour': 4,
    'automatic_default': False,
    'profiles': {
        'Fresco': {'throttle_max': 99, 'boost_mode': 0},
        'Contencao': {'throttle_max': 80, 'boost_mode': 0},
    },
}
PROCESSES = {
    'sample_ms': 2000, 'top': 25, 'busy_cores': 0.5, 'orphan_idle_minutes': 10, 'wait_seconds': 6,
    'automatic_executor': False,
    'agent_names': ['claude', 'codex', 'node', 'bun', 'deno', 'python', 'pythonw', 'uv',
                    'powershell', 'pwsh', 'cmd', 'conhost', 'bash', 'git', 'rg', 'npm', 'npx'],
    'protected_names': ['system', 'registry', 'smss', 'csrss', 'wininit', 'winlogon', 'services',
                        'lsass', 'lsaiso', 'svchost', 'fontdrvhost', 'dwm', 'explorer', 'sihost',
                        'taskhostw', 'ctfmon', 'runtimebroker', 'searchhost', 'searchindexer',
                        'startmenuexperiencehost', 'shellexperiencehost', 'shellhost',
                        'textinputhost', 'applicationframehost', 'securityhealthsystray',
                        'securityhealthservice', 'msmpeng', 'nissrv', 'mpdefendercoreservice',
                        'audiodg', 'spoolsv', 'wudfhost', 'dllhost', 'wmiprvse', 'consent',
                        'useroobebroker', 'lockapp', 'logonui', 'userinit', 'msiexec', 'tiworker',
                        'trustedinstaller', 'steam', 'steamwebhelper', 'steamservice',
                        'gameoverlayui', 'handheldcompanion', 'taskmgr'],
}
STARTUP = {'protected_names': ['Steam Deck', 'Steam Deck.lnk', 'Folego', 'SecurityHealth']}
# Serialized logon: one item at a time, only after calm readings. Triage rules for the card
# (SD + Jupiter APU), not benchmarks. An item never launches under stress; it is reported.
# Default orchestration requested by the user on 17/11/2026 (opt-out and undo in Options).
SEQUENCE = {
    'start_after_seconds': 15, 'gap_seconds': 20, 'calm_samples': 2, 'poll_seconds': 5,
    'cpu_max': 50, 'disk_busy_max': 40, 'disk_queue_max': 1, 'temp_max_c': 80,
    'item_timeout_seconds': 600, 'orchestration_default': True,
}


def prompt_catalog() -> list:
    titles = {prompt.key: prompt.title for prompt in PROMPTS}
    return [
        {'key': key, 'name': name, 'items': [
            {'key': item, 'title': titles[item], 'text': prompt_text(item)} for item in items
        ]}
        for key, name, items in PROMPT_CATEGORIES
    ]


def policy() -> dict:
    return {
        'schema': 1,
        'health': asdict(HealthThresholds()),
        'battery_bands': [battery_band(value) for value in range(101)],
        'windows': {
            'commit_attention': 0.85, 'commit_critical': 0.95,
            'cpu_attention': 85, 'cpu_critical': 95,
            'disk_free_attention': 0.20, 'disk_free_critical': 0.10,
            'poll_seconds': 10, 'extended_seconds': 60,
            'persist_seconds': 60, 'notice_cooldown_seconds': 300,
            'automatic_resource_executor': False,
            'thermal': THERMAL,
            'processes': PROCESSES,
            'startup': STARTUP,
            'appearance': appearance(),
            'sequence': SEQUENCE,
            'prompts': prompt_catalog(),
        },
    }


def build(output: Path) -> dict:
    if output.exists():
        raise ValueError('O destino já existe; preserve o pacote ou escolha o destino de build oficial vazio.')
    output.mkdir(parents=True)
    source = ROOT / 'src/folego/windows'
    for name in FILES:
        data = (source / name).read_bytes()
        if name.endswith('.ps1'):
            data = data.removeprefix(b'\xef\xbb\xbf')
            data = b'\xef\xbb\xbf' + data
        (output / name).write_bytes(data)
    (output / 'policy.json').write_text(json.dumps(policy(), indent=2) + '\n', encoding='utf-8')
    shutil.copyfile(ROOT / 'LICENSE', output / 'LICENSE')
    shutil.copyfile(ROOT / 'docs/WINDOWS.md', output / 'LEIA-ME.md')
    manifest = {
        'schema': 1,
        'product': 'Fôlego Windows',
        'version': tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version'],
        'runtime': 'Windows PowerShell 5.1 / .NET Framework / Windows Forms',
        'capabilities': list(CAPABILITIES),
        'files':{file.name: {'bytes': file.stat().st_size, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
                  for file in sorted(output.iterdir()) if file.is_file()},
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/folego-windows')
    args = parser.parse_args()
    manifest = build(args.output.resolve())
    print(json.dumps({'output': str(args.output), 'version': manifest['version'], 'files': len(manifest['files'])}))


if __name__ == '__main__':
    main()
